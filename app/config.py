import os


class Settings:
    def __init__(self) -> None:
        env = os.environ.get
        self.vllm_base_url = env("VLLM_BASE_URL", "http://host.docker.internal:8001/v1")
        self.vllm_model = env("VLLM_MODEL", "drafting")
        self.spec_mode = env("SPEC_MODE", "iwr")
        self.minio_endpoint = env("MINIO_ENDPOINT", "minio:9000")
        self.minio_access_key = env("MINIO_ACCESS_KEY", "minioadmin")
        self.minio_secret_key = env("MINIO_SECRET_KEY", "minioadmin")


settings = Settings()
