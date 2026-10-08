class S3Storage:
    """Production storage. Not built yet: the local build uses LocalStorage."""

    def __init__(self, bucket: str):
        self.bucket = bucket

    def _todo(self):
        raise NotImplementedError(
            "S3 storage is not implemented yet. Local development uses LocalStorage; "
            "implement put/get/delete/exists here with boto3 when deploying."
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._todo()

    def get(self, key: str) -> bytes:
        self._todo()

    def delete(self, key: str) -> None:
        self._todo()

    def exists(self, key: str) -> bool:
        self._todo()
