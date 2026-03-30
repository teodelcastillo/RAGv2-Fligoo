class HealthCheckMiddleware:
    """Allow ALB health checks to bypass ALLOWED_HOSTS validation.

    ECS ALB sends health checks with the task's private IP as Host header,
    which Django rejects. This middleware intercepts /health/ before the
    security middleware runs and delegates to the health view directly.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/health/":
            from main.health import health_check

            return health_check(request)
        return self.get_response(request)
