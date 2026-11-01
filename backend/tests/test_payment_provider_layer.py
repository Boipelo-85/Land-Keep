from app.services.money import cents_to_zar, zar_to_cents
from app.services.payment_providers import CheckoutRequest, MockProvider, get_payment_provider


def test_money_conversions_use_integer_cents():
    assert zar_to_cents("1234.56") == 123456
    assert cents_to_zar(123456).as_tuple().exponent == -2


def test_mock_provider_builds_checkout_without_network(monkeypatch):
    monkeypatch.setenv("MOCK_PAYMENT_RESULT", "pending")
    provider = get_payment_provider("mock")
    request = CheckoutRequest(
        our_reference="LK-test-reference", amount_cents=125050,
        item_name="Rent October - Unit 4B", buyer_name="Tenant Test",
        buyer_email="tenant@example.test", return_url="http://localhost/return",
        cancel_url="http://localhost/cancel", notify_url="http://localhost/notify",
    )

    result = provider.create_checkout(request)

    assert isinstance(provider, MockProvider)
    assert result.simulated_status == "pending"
    assert result.fields["amount_cents"] == "125050"
    assert "LK-test-reference" in result.redirect_url


def test_mock_notification_parser_maps_results():
    parsed = MockProvider().parse_notification({
        "reference": "LK-test-reference", "amount_cents": "25000", "status": "success",
    })

    assert parsed.our_reference == "LK-test-reference"
    assert parsed.amount_cents == 25000
    assert parsed.status == "succeeded"
