import os
import signal
import sys

import requests
from flask import Flask, jsonify
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "checkout")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
ENVIRONMENT = os.getenv("DEPLOYMENT_ENVIRONMENT", "demo")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "otel-collector:4317")
METRIC_INTERVAL = int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", "10000"))  # ms
SHIPPING_URL = os.getenv("SHIPPING_URL", "http://chaos-proxy:8080")


resource = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": SERVICE_VERSION,
        "deployment.environment": ENVIRONMENT,
        "service.instance.id": os.getenv("HOSTNAME", "checkout-1"),
    }
)


trace.set_tracer_provider(TracerProvider(resource=resource))
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
)

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTLP_ENDPOINT, insecure=True),
    export_interval_millis=METRIC_INTERVAL,
)
metrics.set_meter_provider(
    MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
    )
)

tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

request_counter = meter.create_counter(
    name="http_requests",
    description="Total HTTP requests handled by the checkout service",
    unit="1",
)


app = Flask(__name__)

FlaskInstrumentor().instrument_app(app)

RequestsInstrumentor().instrument()


@app.route("/checkout")
def checkout():
    with tracer.start_as_current_span("checkout-handler") as span:
        status = 500
        try:
            resp = requests.get(f"{SHIPPING_URL}/ship", timeout=5)
            status = resp.status_code
        except requests.RequestException as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
        else:
            if status >= 500:
                span.set_status(Status(StatusCode.ERROR, f"upstream returned {status}"))

        span.set_attribute("http.status_code", status)
        span.set_attribute("upstream.service", "shipping")

        # Uma linha por requisição — o label 'service' é o que o slo.yaml usa.
        request_counter.add(
            1,
            {
                "service": SERVICE_NAME,
                "status_code": str(status),
            },
        )

        if status == 200:
            return jsonify({"status": "ok", "service": SERVICE_NAME}), 200
        return jsonify(
            {
                "status": "error",
                "service": SERVICE_NAME,
                "upstream_status": status,
            }
        ), 500


@app.route("/health")
def health():
    """Liveness probe. NÃO é contabilizado no SLI (não é tráfego do usuário)."""
    return "ok", 200


def _graceful_shutdown(signum, _frame):
    try:
        metrics.get_meter_provider().shutdown()
        trace.get_tracer_provider().shutdown()
    finally:
        sys.exit(0)


signal.signal(signal.SIGTERM, _graceful_shutdown)
signal.signal(signal.SIGINT, _graceful_shutdown)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
