import concurrent.futures
from fastapi.testclient import TestClient
from main import app, reset_fixture

def test_concurrency_race_condition():
    # Reset the stock to 1
    reset_fixture()
    
    client = TestClient(app)
    
    def send_request():
        return client.post("/orders/1", json={"quantity": 1})
        
    # Run 2 concurrent requests to purchase 1 ticket each when stock is 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(send_request) for _ in range(2)]
        responses = [f.result() for f in futures]
        
    success_responses = [r for r in responses if r.status_code == 201]
    
    # If the race condition is present, both requests will succeed (status_code 201),
    # meaning 2 tickets were sold when only 1 was available.
    assert len(success_responses) == 1, f"Race condition allowed {len(success_responses)} successful orders when stock was only 1"
