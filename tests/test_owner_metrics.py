from reachsocial.api import owner_overview
from reachsocial.models import Client, PaymentReceipt, ProviderAttempt, RequestLog


def test_owner_revenue_does_not_double_count_x402(session, client, catalog) -> None:
    public = Client(
        name="x402-public",
        api_key_hash="not-used",
        billing_mode="external",
    )
    session.add(public)
    session.flush()
    session.add_all(
        [
            RequestLog(
                request_id="req_public",
                client_id=public.id,
                service_id="instagram.profile",
                status="success",
                charged_cents=5,
                input_hash="hash-public",
            ),
            RequestLog(
                request_id="req_b2b",
                client_id=client.id,
                service_id="instagram.profile",
                status="success",
                charged_cents=10,
                input_hash="hash-b2b",
            ),
            PaymentReceipt(
                payment_id="payment-public",
                service_id="instagram.profile",
                amount_cents=5,
                network="eip155:84532",
                status="settled",
            ),
            ProviderAttempt(
                request_id="req_public",
                service_id="instagram.profile",
                provider="mock",
                status="succeeded",
                upstream_cost_microusd=1000,
                public_test=True,
            ),
        ]
    )
    session.commit()
    result = owner_overview(session=session, catalog=catalog, _admin=None)
    assert result["revenue_cents"] == 15
    assert result["margin_microusd"] == 149_000
    assert result["services"]["instagram.profile"]["revenue_cents"] == 15
    assert result["services"]["instagram.profile"]["upstream_cost_microusd"] == 1000
