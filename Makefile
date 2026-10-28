.PHONY: generate-rules demo clean

generate-rules:
	mkdir -p prometheus/rules
	docker run --rm \
		-v $(PWD)/sloth/slo.yaml:/slo.yaml \
		-v $(PWD)/prometheus/rules:/output \
		slok/sloth:latest \
		generate -i /slo.yaml -o /output/slo-rules.yaml

demo: generate-rules
	docker compose up --build

clean:
	docker compose down -v
	rm -rf prometheus/rules
