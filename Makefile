ROOT_DIR := $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST))))
BUILD_DIR := $(ROOT_DIR)/build
DIST_DIR := $(BUILD_DIR)/dist
GIT_COMMIT := $(shell git rev-parse HEAD)

AWS_REGION ?= us-west-2
S3_BUCKET ?= infinity-artifacts
# Default to putting artifacts under a random directory, which will get cleaned up automatically:
S3_PREFIX ?= autodelete7d/spark/test-`date +%Y%m%d-%H%M%S`-`cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 16 | head -n 1`
SPARK_REPO_URL ?= https://github.com/mesosphere/spark

.ONESHELL:
SHELL := /bin/bash
.SHELLFLAGS = -ec

# This image can be used to build spark dist and run tests
DOCKER_BUILD_IMAGE ?= mesosphere/spark-build:$(GIT_COMMIT)
docker-build:
	docker build -t $(DOCKER_BUILD_IMAGE) .
	echo $(DOCKER_BUILD_IMAGE) > $@

HADOOP_VERSION ?= $(shell jq ".default_spark_dist.hadoop_version" "$(ROOT_DIR)/manifest.json")
SPARK_DIR ?= $(ROOT_DIR)/spark
$(SPARK_DIR):
	git clone $(SPARK_REPO_URL) $(SPARK_DIR)

prod-dist: $(SPARK_DIR)
	pushd $(SPARK_DIR)
	rm -rf spark-*.tgz
	if [ -n "$(does_profile_exist,mesos)" ]; then
		MESOS_PROFILE="-Pmesos"
	else
		MESOS_PROFILE=""
	fi
	./dev/make-distribution.sh --tgz "$${MESOS_PROFILE}" "-Phadoop-$(HADOOP_VERSION)" -Pnetlib-lgpl -Psparkr -Phive -Phive-thriftserver -DskipTests
	filename=`ls spark-*.tgz`
	rm -rf $(DIST_DIR)
	mkdir -p $(DIST_DIR)
	mv $${filename} $(DIST_DIR)
	echo "Built: $(DIST_DIR)/$${filename}"

# If build/dist/ doesn't exist, creates it and downloads the spark build in manifest.json.
# To instead use a locally built version of spark, you must run "make prod-dist".
SPARK_DIST_URI ?= $(shell jq ".default_spark_dist.uri" "$(ROOT_DIR)/manifest.json")
$(DIST_DIR):
	mkdir -p $(DIST_DIR)
	pushd $(DIST_DIR)
	wget $(SPARK_DIST_URI)
	popd

clean-dist:
	rm -f $(ROOT_DIR)/docker-dist
	rm -rf $(DIST_DIR)

docker-login:
	docker login --email="$(DOCKER_EMAIL)" --username="$(DOCKER_USERNAME)" --password="$(DOCKER_PASSWORD)"

DOCKER_DIST_IMAGE ?= mesosphere/spark-dev:$(GIT_COMMIT)
docker-dist: $(DIST_DIR)
	SPARK_BUILDS=`ls $(DIST_DIR)/spark-*.tgz || exit 0`
	if [ `echo "$${SPARK_BUILDS}" | wc -w` == 1 ]; then
		echo "Using spark: $${SPARK_BUILDS}"
	else
		echo "Should have a single Spark package in $(DIST_DIR), found: $${SPARK_BUILDS}"
		echo "Delete the ones you don't want?"
		exit 1
	fi
	tar xvf $${SPARK_BUILDS} -C $(DIST_DIR)

	rm -rf $(BUILD_DIR)/docker
	mkdir -p $(BUILD_DIR)/docker/dist
	cp -r $(DIST_DIR)/spark-*/. $(BUILD_DIR)/docker/dist
	cp -r conf/* $(BUILD_DIR)/docker/dist/conf
	cp -r docker/* $(BUILD_DIR)/docker

	pushd $(BUILD_DIR)/docker
	docker build -t $(DOCKER_DIST_IMAGE) .
	popd

	docker push $(DOCKER_DIST_IMAGE)
	echo "$(DOCKER_DIST_IMAGE)" > $@

cli:
	$(ROOT_DIR)/cli/dcos-spark/build.sh

UNIVERSE_URL_PATH ?= $(ROOT_DIR)/spark-universe-url
stub-universe-url: docker-dist cli
	if [ -n "$(STUB_UNIVERSE_URL)" ]; then
		echo "Using provided stub universe(s): $(STUB_UNIVERSE_URL)"
		echo "$(STUB_UNIVERSE_URL)" > $(UNIVERSE_URL_PATH)
	else
		UNIVERSE_URL_PATH=$(ROOT_DIR)/stub-universe-url.tmp \
		TEMPLATE_DEFAULT_DOCKER_IMAGE=`cat docker-dist` \
		TEMPLATE_HTTPS_PROTOCOL='https://' \
		        $(ROOT_DIR)/tools/build_package.sh spark-history $(ROOT_DIR)/history aws
		cat $(ROOT_DIR)/stub-universe-url.tmp > $(UNIVERSE_URL_PATH)

		UNIVERSE_URL_PATH=$(ROOT_DIR)/stub-universe-url.tmp \
		TEMPLATE_DOCKER_IMAGE=`cat docker-dist` \
		TEMPLATE_HTTPS_PROTOCOL='https://' \
			$(ROOT_DIR)/tools/build_package.sh \
			spark \
			$(ROOT_DIR) \
			-a $(ROOT_DIR)/cli/dcos-spark/dcos-spark-darwin \
			-a $(ROOT_DIR)/cli/dcos-spark/dcos-spark-linux \
			-a $(ROOT_DIR)/cli/dcos-spark/dcos-spark.exe \
			aws
		cat $(ROOT_DIR)/stub-universe-url.tmp >> $(UNIVERSE_URL_PATH)

		rm -f $(ROOT_DIR)/stub-universe-url.tmp
	fi


DCOS_SPARK_TEST_JAR_PATH ?= $(ROOT_DIR)/dcos-spark-scala-tests-assembly-0.1-SNAPSHOT.jar
$(DCOS_SPARK_TEST_JAR_PATH):
	cd tests/jobs/scala
	sbt assembly
	cp $(ROOT_DIR)/tests/jobs/scala/target/scala-2.11/dcos-spark-scala-tests-assembly-0.1-SNAPSHOT.jar $(DCOS_SPARK_TEST_JAR_PATH)

clean-cluster:
	dcos-launch delete || echo "Error deleting cluster"

mesos-spark-integration-tests:
	git clone https://github.com/typesafehub/mesos-spark-integration-tests $(ROOT_DIR)/mesos-spark-integration-tests

MESOS_SPARK_TEST_JAR_PATH ?= $(ROOT_DIR)/mesos-spark-integration-tests-assembly-0.1.0.jar
$(MESOS_SPARK_TEST_JAR_PATH): mesos-spark-integration-tests
	cd $(ROOT_DIR)/mesos-spark-integration-tests/test-runner
	sbt assembly
	cd ..
	sbt clean compile test
	cp test-runner/target/scala-2.11/mesos-spark-integration-tests-assembly-0.1.0.jar $(MESOS_SPARK_TEST_JAR_PATH)

CF_TEMPLATE_URL ?= https://s3.amazonaws.com/downloads.mesosphere.io/dcos-enterprise/testing/master/cloudformation/ee.single-master.cloudformation.json
write-config-yaml:
	$(eval export DCOS_LAUNCH_CONFIG_BODY)
	echo "$$DCOS_LAUNCH_CONFIG_BODY" > $(ROOT_DIR)/config.yaml

test: $(DCOS_SPARK_TEST_JAR_PATH) $(MESOS_SPARK_TEST_JAR_PATH) write-config-yaml stub-universe-url
	if [ -z "$(CLUSTER_URL)" ]; then
		rm -f $(ROOT_DIR)/cluster_info.json # TODO remove this when launch_cluster.sh in docker image is updated
	fi
	STUB_UNIVERSE_URL=`cat $(UNIVERSE_URL_PATH)` \
	CUSTOM_DOCKER_ARGS="\
-e DCOS_SPARK_TEST_JAR_PATH=/build/`basename ${DCOS_SPARK_TEST_JAR_PATH}` \
-e MESOS_SPARK_TEST_JAR_PATH=/build/`basename ${MESOS_SPARK_TEST_JAR_PATH}` \
-e S3_PREFIX=$(S3_PREFIX) \
-e S3_BUCKET=$(S3_BUCKET) \
-e AWS_REGION=$(AWS_REGION)" \
	S3_BUCKET=$(S3_BUCKET) \
		$(ROOT_DIR)/test.sh

clean: clean-dist
	for f in  "$(MESOS_SPARK_TEST_JAR_PATH)" "$(DCOS_SPARK_TEST_JAR_PATH)" "$(UNIVERSE_URL_PATH)" "docker-build"; do
		[ ! -e $$f ] || rm $$f
	done



define spark_dist
`cd $(DIST_DIR) && ls spark-*.tgz`
endef

define does_profile_exist
`cd "$(SPARK_DIR)" && ./build/mvn help:all-profiles | grep $(1)`
endef

define DCOS_LAUNCH_CONFIG_BODY
---
launch_config_version: 1
deployment_name: dcos-ci-test-spark-build-$(shell cat /dev/urandom | tr -dc 'a-z0-9' | fold -w 10 | head -n 1)
template_url: $(CF_TEMPLATE_URL)
provider: aws
key_helper: true
template_parameters:
  AdminLocation: 0.0.0.0/0
  PublicSlaveInstanceCount: 1
  SlaveInstanceCount: 5
ssh_user: core
endef

.PHONY: clean clean-dist cli stub-universe-url prod-dist docker-login test
