import concurrent.futures
from fastapi.testclient import TestClient
from main import app, STATE, reset_state

def test_concurrent_orders_oversell():
    reset_state()
    client = TestClient(app)
    
    def place_order(user, key):
        try:
            response = client.post(
                "/orders",
                headers={
                    "Authorization": f"Bearer {user}",
                    "Idempotency-Key": key
                },
                json={"product_id": 1, "quantity": 5}
            )
            return response
        except Exception as e:
            return e

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(place_order, "buyer-a", "key-1"),
            executor.submit(place_order, "buyer-b", "key-2")
        ]
        results = [f.result() for f in futures]

    success_count = sum(1 for r in results if hasattr(r, "status_code") and r.status_code == 201)
    conflict_count = sum(1 for r in results if hasattr(r, "status_code") and r.status_code == 409)
    
    assert success_count == 1, f"Expected exactly 1 successful order, got {success_count}"
    assert conflict_count == 1, f"Expected exactly 1 conflict (409), got {conflict_count}"
    assert STATE.stock >= 0, f"Stock should not be negative, got {STATE.stock}"
