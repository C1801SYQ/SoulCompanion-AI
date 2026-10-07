"""Public failures never include upstream response bodies or credentials."""


class CloudError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


def unavailable() -> CloudError:
    return CloudError(
        503, "service_unavailable", "Cloud service is temporarily unavailable."
    )


def not_found() -> CloudError:
    return CloudError(404, "not_found", "Record not found.")
