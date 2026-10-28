import os

import requests
from flask import Flask, jsonify
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

app = Flask(__name__)

# OpenTelemetry setup
trace.set_tracer_provider(TracerProvider())
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="otel-collector:4317", insecure=True))
)

metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint="otel-collector:4317", insecure=True)
)
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))

FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

# Contador de requisições (SLI de disponibilidade)
request_counter = meter.create_counter(
    "http_requests_total",
    description="Total HTTP requests",
    unit="1",
)

SHIPPING_URL = os.getenv("SHIPPING_URL", "http://chaos-proxy:8080")


@app.route("/checkout")
def checkout():
    with tracer.start_as_current_span("checkout-handler") as span:
        try:
            # Chamada ao shipping (passa pelo proxy de caos)
            resp = requests.get(f"{SHIPPING_URL}/ship", timeout=5)
            status = resp.status_code
        except Exception:
            status = 500

        request_counter.add(1, {"service": "checkout", "status_code": str(status)})
        span.set_attribute("http.status_code", status)

        if status == 200:
            return jsonify({"status": "ok", "service": "checkout"}), 200
        else:
            return jsonify({"status": "error", "service": "checkout"}), 500


@app.route("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
