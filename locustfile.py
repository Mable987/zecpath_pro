from locust import HttpUser, task, between
 
 
class AnonymousBrowser(HttpUser):
    """Most traffic: unauthenticated visitors browsing public jobs."""
    wait_time = between(1, 3)
    weight = 5  # 5x more of these than the authenticated user below
 
    @task(3)
    def browse_public_jobs(self):
        self.client.get("/api/public/jobs/")
 
    @task(1)
    def browse_featured_jobs(self):
        self.client.get("/api/public/jobs/featured/")
 
    @task(1)
    def browse_latest_jobs(self):
        self.client.get("/api/public/jobs/latest/")
 
 
class AuthenticatedCandidate(HttpUser):
    """A smaller slice: logged-in candidates checking their dashboard."""
    wait_time = between(2, 5)
    weight = 1
 
    def on_start(self):
        """Log in once per simulated user, reuse the token for all
        subsequent requests — this mirrors how a real client behaves,
        not re-authenticating on every single request."""
        response = self.client.post("/api/login/", json={
            "email": "nico@gmail.com",       
            "password": "nico12345",
        })
        if response.status_code == 200:
            token = response.json().get("access")
            self.client.headers.update({"Authorization": f"Bearer {token}"})
 
    @task
    def view_dashboard(self):
        self.client.get("/api/candidate/dashboard/")
 
    @task
    def view_applications(self):
        self.client.get("/api/applications/")