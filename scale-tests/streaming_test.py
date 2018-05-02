import json
import sys

import sdk_cmd
import shakedown
import spark_utils as utils
from tests import test_kafka

KAFKA_PACKAGE_NAME = "kafka"
KAFKA_SERVICE_NAME = "kafka"
PRODUCER_SERVICE_NAME = "Spark->Kafka Producer"


def run_pipeline(kerberos_flag, num_consumers, stop_count, jar_uri, spark_app_name):
    stop_count = str(stop_count)
    broker_dns = _kafka_broker_dns()
    topic = "top1"

    big_file, big_file_url = "file:///mnt/mesos/sandbox/big.txt", "http://norvig.com/big.txt"

    # arguments to the application
    producer_args = " ".join([broker_dns, big_file, topic, kerberos_flag])

    uris = "spark.mesos.uris=http://norvig.com/big.txt"

    common_args = [
        "--conf", "spark.mesos.containerizer=mesos",
        "--conf", "spark.scheduler.maxRegisteredResourcesWaitingTime=2400s",
        "--conf", "spark.scheduler.minRegisteredResourcesRatio=1.0",
        "--conf", uris
    ]

    producer_config = ["--conf", "spark.cores.max=2", "--conf", "spark.executor.cores=2",
                       "--class", "KafkaFeeder"] + common_args

    producer_id = utils.submit_job(app_url=jar_uri,
                                   app_args=producer_args,
                                   app_name=spark_app_name,
                                   args=producer_config,
                                   verbose=False)

    shakedown.wait_for(lambda: test_kafka._producer_launched(), ignore_exceptions=False, timeout_seconds=600)
    # shakedown.wait_for(lambda: utils.is_service_ready(KAFKA_SERVICE_NAME, 1),
    #                   ignore_exceptions=False, timeout_seconds=600)

    consumer_config = ["--conf", "spark.cores.max=4", "--class", "KafkaConsumer"] + common_args

    consumer_args = " ".join([broker_dns, topic, stop_count, kerberos_flag])

    for i in range(0, num_consumers):
        utils.run_tests(app_url=jar_uri,
                        app_args=consumer_args,
                        expected_output="Read {} words".format(stop_count),
                        app_name=spark_app_name,
                        args=consumer_config)

    utils.kill_driver(producer_id, spark_app_name)


def _kafka_broker_dns():
    cmd = "{package_name} --name={service_name} endpoints broker".format(
        package_name=KAFKA_PACKAGE_NAME, service_name=KAFKA_SERVICE_NAME)
    rt, stdout, stderr = sdk_cmd.run_raw_cli(cmd)
    assert rt == 0, "Failed to get broker endpoints"
    return json.loads(stdout)["dns"][0]


if __name__ == "__main__":
    usage = """
        Setup: export PYTHONPATH=../spark-testing:../testing:../tests
        Usage: python streaming_test.py number_of_consumers [stop_count]
    """

    if len(sys.argv) < 3:
        print(usage)
        sys.exit(2)

    jar_uri = "https://s3-us-west-2.amazonaws.com/infinity-artifacts/soak/spark/dcos-spark-scala-tests-assembly-0.1-SNAPSHOT.jar"

    num_consumers = sys.argv[1]
    print("num_consumers: {}".format(num_consumers))

    stop_count = sys.argv[2]
    print("stop_count: {}".format(stop_count))

    run_pipeline(kerberos_flag="false",
                 jar_uri=jar_uri,
                 num_consumers=num_consumers,
                 stop_count=stop_count,
                 spark_app_name=utils.SPARK_APP_NAME)

    # dispatchers_file = sys.argv[1]
    # print("dispatchers_file: {}".format(dispatchers_file))
    # with open(dispatchers_file) as f:
    #     dispatchers = f.read().splitlines()
    # print("dispatchers: {}".format(dispatchers))
    #
    # launch_rate_per_min = int(sys.argv[2])
    # print("launch_rate_per_min: {}".format(launch_rate_per_min))
    #
    # submit_loop(launch_rate_per_min, dispatchers)
