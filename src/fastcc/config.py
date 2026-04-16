from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CrankerConnectorConfig:
    router_urls: list[str]
    route: str
    domain: str = "*"
    component_name: str = "fast-cc"
    connector_instance_id: str | None = None
    preferred_protocols: list[str] = field(default_factory=lambda: ["cranker_3.0"])
    sliding_window_size: int = 2
    ping_interval_seconds: float = 5.0
    idle_timeout_seconds: float = 20.0
    deregister_timeout_seconds: float = 60.0
    flow_control_high_watermark: int = 64 * 1024
    flow_control_low_watermark: int = 16 * 1024
    forwarded_scheme: str | None = None
    verify_ssl: bool = True
    reconnect_delay_seconds: float = 1.0
