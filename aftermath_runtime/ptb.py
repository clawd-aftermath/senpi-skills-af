"""Transaction pipeline: build -> preview gate -> INSPECT -> (sign) -> reconcile.

Copyright 2026 Aftermath Finance.
SPDX-License-Identifier: MIT

A builder response is untrusted input.  Between "the server handed me a
transaction" and "I signed it" there must be a step that proves the transaction
is the one we asked for, and that step must be impossible to skip.

The gate is enforced structurally, not by convention.  ``InspectedTx`` cannot
be constructed without a module-private token that only :func:`inspect`
possesses, and :func:`sign_inspected` accepts nothing else.  There is no path
from a raw builder response to a signature that bypasses inspection.

**Nothing in this module signs, submits, or broadcasts.**  ``sign_inspected``
takes a caller-supplied callback; this repository ships without one wired up
and refuses to run unless the runtime has been explicitly armed.

Response shape, verified against the live V2 spec — do NOT assume the shape
another Aftermath client uses:

* every ``/api/perpetuals/**/transactions/*`` route answers
  ``{"txKind": "<base64>", "sponsorSignature": str|null}``.  ``txKind`` is a
  transaction *kind* for client-side PTB composition, not finished
  ``transactionBytes``, and there is no ``signingDigest`` in the response.
* ``/api/perpetuals/transactions/create-account`` additionally answers
  ``{"deferred": {accountArg, adminCapArg, sharePolicyArg,
  collateralCoinType}}`` when ``deferShare = true`` — deferred PTB argument
  references, not just ``{txKind}`` (``gotchas.md`` §12).
* previews answer HTTP 200 with EITHER ``{"error": str}`` OR
  ``{"collateralAmountOut", "collateralPrice"}``.  Parse as a tagged union and
  fail closed (``gotchas.md`` §6).

Signing rule (``gotchas.md`` §2): sign the ``signingDigest``, never
``transactionBytes``.  Once a composed PTB has been finalised locally the
digest is what a signer receives; :func:`sign_inspected` therefore refuses any
inspected transaction that has not had a digest attached.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .errors import (
    ContractError,
    InspectionFailed,
    PreviewRejected,
    WriteDenied,
)
from .gas import GasConfig
from .ids import SuiAddress

# ── Preview tagged union ─────────────────────────────────────────


@dataclass(frozen=True)
class PreviewOk:
    collateral_amount_out: int
    collateral_price: float
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class PreviewError:
    error: str


PreviewResult = PreviewOk | PreviewError


def parse_preview(payload: Any, *, endpoint: str) -> PreviewResult:
    """Parse a preview response as a tagged union, failing closed.

    Anything that is not unambiguously the success arm becomes an error arm.
    A preview endpoint returning HTTP 200 with ``{"error": ...}`` (and the
    ``X-Error-Message: true`` header) is the documented failure mode; treating
    that as success is the bug this function exists to make impossible.
    """
    if not isinstance(payload, Mapping):
        return PreviewError(f"{endpoint}: preview response was not an object")
    error = payload.get("error")
    if error not in (None, "", [], {}):
        return PreviewError(str(error))
    if "collateralAmountOut" not in payload:
        return PreviewError(
            f"{endpoint}: preview response missing collateralAmountOut; "
            "refusing to treat an unrecognised shape as success"
        )
    raw_amount = payload["collateralAmountOut"]
    try:
        amount = (
            int(raw_amount[:-1])
            if isinstance(raw_amount, str) and raw_amount.endswith("n")
            else int(raw_amount)
        )
    except (TypeError, ValueError):
        return PreviewError(f"{endpoint}: collateralAmountOut is not an integer")
    price = payload.get("collateralPrice")
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        return PreviewError(f"{endpoint}: collateralPrice is not numeric")
    return PreviewOk(amount, float(price), payload)


def headers_signal_error(headers: Mapping[str, str] | None) -> bool:
    """``X-Error-Message: true`` accompanies an HTTP-200 preview error body."""
    if not headers:
        return False
    for key, value in headers.items():
        if key.lower() == "x-error-message" and str(value).strip().lower() == "true":
            return True
    return False


# ── Intent ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class TxIntent:
    """What the caller asked for.  Inspection checks the build against this."""

    intent: str
    sender: SuiAddress
    gas: GasConfig
    build_path: str
    expected_package: str | None = None
    expects_deferred: bool = False


# ── The inspection gate ──────────────────────────────────────────

_GATE_TOKEN = object()


@dataclass(frozen=True)
class InspectedTx:
    """A transaction that has passed inspection.

    Construction requires ``_token is _GATE_TOKEN``, a module-private object.
    Only :func:`inspect` holds it, so possessing an ``InspectedTx`` is proof the
    gate ran.

    The token is CLEARED immediately after validation, so it cannot be harvested
    off an existing instance and reused to mint an uninspected one — which also
    means ``dataclasses.replace`` on an ``InspectedTx`` fails rather than
    laundering a mutation past the gate.
    """

    tx_kind: str
    intent: TxIntent
    sponsor_signature: str | None = None
    deferred: Mapping[str, Any] | None = None
    signing_digest: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)
    _token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _GATE_TOKEN:
            raise InspectionFailed(
                "InspectedTx cannot be constructed directly; it is produced "
                "only by inspect(). This gate is not bypassable."
            )
        object.__setattr__(self, "_token", None)

    def with_digest(self, signing_digest: str) -> "InspectedTx":
        """Attach the digest produced by locally finalising the composed PTB.

        The digest is what gets signed.  ``transactionBytes`` never are.
        """
        if not isinstance(signing_digest, str) or not signing_digest:
            raise InspectionFailed("signing digest must be a non-empty string")
        _require_base64(signing_digest, "signingDigest", self.intent.intent)
        return InspectedTx(
            tx_kind=self.tx_kind,
            intent=self.intent,
            sponsor_signature=self.sponsor_signature,
            deferred=self.deferred,
            signing_digest=signing_digest,
            raw=self.raw,
            _token=_GATE_TOKEN,
        )


def _require_base64(value: str, field_name: str, intent: str) -> None:
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InspectionFailed(
            f"transaction inspection failed ({intent}): {field_name} is not "
            "valid base64"
        ) from exc


def _echoed(payload: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def inspect(built: Any, intent: TxIntent) -> InspectedTx:
    """Verify a built transaction matches the intent it was requested for.

    Raises rather than returning a falsy value: an inspection failure must not
    be ignorable by a caller that forgets to check a boolean.

    Asserted: the response is the documented ``{txKind}`` shape; ``txKind`` is
    real base64; the echoed sender (when present) is the expected sender; the
    echoed package (when known) is the expected package; and the gas
    configuration in the response matches the mode the caller selected.
    """
    label = intent.intent
    if not isinstance(built, Mapping):
        raise InspectionFailed(
            f"transaction inspection failed ({label}): builder returned "
            f"{type(built).__name__}, not an object"
        )

    tx_kind = built.get("txKind")
    if not isinstance(tx_kind, str) or not tx_kind:
        raise InspectionFailed(
            f"transaction inspection failed ({label}): response carries no "
            "txKind. Every V2 transaction route returns {txKind}; a response "
            "without one is not a transaction this runtime will sign."
        )
    _require_base64(tx_kind, "txKind", label)

    if "transactionBytes" in built and "signingDigest" not in built:
        # Guard against a client that grew a habit of signing raw bytes.
        raise InspectionFailed(
            f"transaction inspection failed ({label}): response carries "
            "transactionBytes with no signingDigest — refusing to sign "
            "transaction bytes directly"
        )

    echoed_sender = _echoed(built, ("walletAddress", "sender", "from"))
    if echoed_sender and echoed_sender.lower() != str(intent.sender).lower():
        raise InspectionFailed(
            f"transaction inspection failed ({label}): sender mismatch — "
            f"expected {intent.sender}, transaction is for {echoed_sender}"
        )

    echoed_package = _echoed(built, ("packageId", "package"))
    if (
        intent.expected_package
        and echoed_package
        and echoed_package != intent.expected_package
    ):
        raise InspectionFailed(
            f"transaction inspection failed ({label}): package mismatch — "
            f"expected {intent.expected_package}, transaction targets "
            f"{echoed_package}"
        )

    sponsor_signature = built.get("sponsorSignature")
    if sponsor_signature is not None and not isinstance(sponsor_signature, str):
        raise InspectionFailed(
            f"transaction inspection failed ({label}): sponsorSignature must be "
            "a string or null"
        )

    # Gas mode consistency.  Sponsor and sender MAY be the same Sui address, so
    # only the presence/absence of sponsorship is checked, never inequality.
    if intent.gas.mode == "self" and sponsor_signature:
        raise InspectionFailed(
            f"transaction inspection failed ({label}): gas mode is 'self' but "
            "the builder returned a sponsor signature"
        )
    if intent.gas.mode == "sponsored" and sponsor_signature is None:
        raise InspectionFailed(
            f"transaction inspection failed ({label}): gas mode is 'sponsored' "
            "but the builder returned no sponsor signature"
        )

    deferred = built.get("deferred")
    if intent.expects_deferred:
        if not isinstance(deferred, Mapping):
            raise InspectionFailed(
                f"transaction inspection failed ({label}): deferShare=true was "
                "requested but the response carries no deferred PTB argument "
                "references"
            )
        missing = {"accountArg", "adminCapArg", "sharePolicyArg"} - set(deferred)
        if missing:
            raise InspectionFailed(
                f"transaction inspection failed ({label}): deferred references "
                f"missing {sorted(missing)}"
            )
    elif deferred is not None and not isinstance(deferred, Mapping):
        raise InspectionFailed(
            f"transaction inspection failed ({label}): deferred must be an "
            "object or null"
        )

    return InspectedTx(
        tx_kind=tx_kind,
        intent=intent,
        sponsor_signature=sponsor_signature,
        deferred=deferred if isinstance(deferred, Mapping) else None,
        raw=built,
        _token=_GATE_TOKEN,
    )


# ── Signing (caller-supplied; nothing here signs) ────────────────

SignFn = Callable[[str], str]
"""Signs the DIGEST.  Never the transaction bytes."""


def sign_inspected(
    tx: InspectedTx,
    signers: Sequence[SignFn],
    *,
    armed: bool = False,
) -> list[str]:
    """Produce signatures for an inspected transaction.

    ``/api/ccxt/submit/*`` takes ``signatures[]``, plural (``gotchas.md`` §14):
    when the sender and the gas owner differ, both sign the SAME digest.  Hence
    a list, always.

    Refuses unless the runtime is explicitly armed.  This repository ships
    ``armed=False`` and with no signer implementations at all.
    """
    if not isinstance(tx, InspectedTx):
        raise InspectionFailed(
            "sign_inspected accepts only an InspectedTx produced by inspect()"
        )
    if not armed:
        raise WriteDenied(
            "runtime is not armed; set AF_ARMED=1 and supply a signer to "
            "produce signatures. Nothing in this repository signs by default."
        )
    if tx.signing_digest is None:
        raise InspectionFailed(
            "no signing digest attached: finalise the composed PTB and call "
            "InspectedTx.with_digest() first. Never sign transactionBytes."
        )
    if not signers:
        raise WriteDenied("no signers supplied")
    return [sign(tx.signing_digest) for sign in signers]


def submit(*_args: Any, **_kwargs: Any) -> None:
    """Explicitly unimplemented.

    Submission is out of scope for this repository by policy: no transaction
    may be signed, submitted, or broadcast.  The stub exists so that a caller
    reaching for it gets a clear refusal instead of finding a plausible helper.
    """
    raise WriteDenied(
        "submission is not implemented: this runtime never broadcasts. "
        "Build, preview and inspect only."
    )


# ── The gated build pipeline ─────────────────────────────────────


class PtbPipeline:
    """build -> preview gate -> inspect, over an injected transport.

    ``transport.post(path, body)`` is the only I/O.  The preview runs FIRST
    where a counterpart exists, and a preview error blocks the build entirely —
    no transaction is constructed for something already known to fail.
    """

    def __init__(self, transport: Any) -> None:
        self._transport = transport

    def preview(self, path: str, body: Mapping[str, Any]) -> PreviewResult:
        try:
            payload = self._transport.post(path, dict(body))
        except Exception as exc:  # noqa: BLE001 - fail closed on any transport error
            return PreviewError(f"{path}: {exc}")
        return parse_preview(payload, endpoint=path)

    def build(
        self,
        intent: TxIntent,
        body: Mapping[str, Any],
        *,
        preview_path: str | None = None,
        preview_body: Mapping[str, Any] | None = None,
    ) -> InspectedTx:
        gassed = intent.gas.apply_to_body(body)
        if preview_path:
            result = self.preview(preview_path, preview_body or body)
            if isinstance(result, PreviewError):
                raise PreviewRejected(
                    f"preview rejected {intent.intent}: {result.error}"
                )
        built = self._transport.post(intent.build_path, gassed)
        return inspect(built, intent)


# ── Reconciliation ───────────────────────────────────────────────


def reconcile(
    verify: Callable[[], bool],
    *,
    attempts: int = 5,
    intent: str = "operation",
    sleep: Callable[[float], None] = lambda _seconds: None,
    delay_seconds: float = 0.4,
) -> None:
    """Confirm the intent actually took effect by re-reading authoritative state.

    A 200 from submit means "accepted", not "applied".  Never treat it as final
    truth.  ``verify`` re-reads from the API and returns True only when the
    expected end state is observed.
    """
    if attempts < 1:
        raise ContractError("reconcile needs at least one attempt")
    for index in range(attempts):
        if verify():
            return
        if index < attempts - 1:
            sleep(delay_seconds * (index + 1))
    raise ContractError(
        f"reconciliation failed ({intent}): expected state not observed after "
        f"{attempts} attempts"
    )
