import json
import sys

import sdk_cmd
import spark_utils as utils

KAFKA_PACKAGE_NAME = "kafka"
KAFKA_SERVICE_NAME = "kafka"
PRODUCER_SERVICE_NAME = "Spark->Kafka Producer"
KERBEROS_FLAG = "false"
JAR_URI = "https://s3-us-west-2.amazonaws.com/infinity-artifacts/soak/spark/dcos-spark-scala-tests-assembly-0.1-SNAPSHOT.jar"
PRODUCER_AVG_NUM_WORDS_PER_MIN = 500


def run_pipeline(num_consumers, desired_runtime, spark_app_name):
    broker_dns = _kafka_broker_dns()
    topic = "topic-{}".format(spark_app_name)

    num_words_to_read = int(desired_runtime * PRODUCER_AVG_NUM_WORDS_PER_MIN / num_consumers)

    # arguments to the application
    common_args = [
        "--conf", "spark.scheduler.maxRegisteredResourcesWaitingTime=2400s",
        "--conf", "spark.scheduler.minRegisteredResourcesRatio=1.0",
        "--conf", "spark.mesos.containerizer=mesos",
        "--conf", "mesosphere/spark-dev:f5dd540adffd9ab9e3e826e48d22e39ebc296567-1d7926a8b500d0105b80a6bb808a671b047dc963",
        "--conf", "spark.mesos.uris=http://norvig.com/big.txt"
    ]

    _submit_producer(broker_dns, common_args, topic, spark_app_name)

    for i in range(0, num_consumers):
        _submit_consumers(broker_dns, common_args, topic, spark_app_name, str(num_words_to_read))


def _kafka_broker_dns():
    cmd = "{package_name} --name={service_name} endpoints broker".format(
        package_name=KAFKA_PACKAGE_NAME,
        service_name=KAFKA_SERVICE_NAME)
    rt, stdout, _ = sdk_cmd.run_raw_cli(cmd)
    assert rt == 0, "Failed to get broker endpoints"
    return json.loads(stdout)["dns"][0]


def _submit_producer(broker_dns, args, topic, spark_app_name):
    big_file = "file:///mnt/mesos/sandbox/big.txt"

    producer_args = " ".join([broker_dns, big_file, topic, KERBEROS_FLAG])

    producer_config = ["--conf", "spark.cores.max=2",
                       "--conf", "spark.executor.cores=2",
                       "--class", "KafkaFeeder"] + args

    utils.submit_job(app_url=JAR_URI,
                     app_args=producer_args,
                     app_name=spark_app_name,
                     args=producer_config,
                     verbose=False)


def _submit_consumers(broker_dns, args, topic, spark_app_name, num_words):
    consumer_args = " ".join([broker_dns, topic, num_words, KERBEROS_FLAG])

    consumer_config = ["--conf", "spark.cores.max=4",
                       "--class", "KafkaConsumer"] + args

    utils.submit_job(app_url=JAR_URI,
                     app_args=consumer_args,
                     app_name=spark_app_name,
                     args=consumer_config,
                     verbose=False)


if __name__ == "__main__":
    usage = """
        Setup: export PYTHONPATH=../spark-testing:../testing:../tests
        Usage: python streaming_test.py [dispatcher_file] [num_consumers_per_producer] [desired_runtime_in_mins]
    """

    if len(sys.argv) < 4:
        print(usage)
        sys.exit(2)

    dispatchers_file = sys.argv[1]
    print("dispatchers_file: {}".format(dispatchers_file))
    with open(dispatchers_file) as f:
        dispatchers = f.read().splitlines()
    print("dispatchers: {}".format(dispatchers))

    num_consumers = int(sys.argv[2])
    print("num_consumers_per_producer: {}".format(num_consumers))

    desired_runtime = int(sys.argv[3])
    print("desired_runtime_in_mins: {}".format(desired_runtime))

    print("Installing kafka CLI...")
    rc, stdout, stderr = sdk_cmd.run_raw_cli("package install {} --yes --cli".format(KAFKA_PACKAGE_NAME))

    for dispatcher_name in dispatchers:
        run_pipeline(num_consumers=num_consumers,
                     desired_runtime=desired_runtime,
                     spark_app_name=dispatcher_name)
