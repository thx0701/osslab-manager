.PHONY: test check
test:
	python3 -m unittest discover -s tests -v
check:
	python3 -m compileall -q osrelay tests
	git diff --check
