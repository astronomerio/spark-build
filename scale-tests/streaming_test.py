import json
import sys

import sdk_cmd
import spark_utils as utils

KAFKA_PACKAGE_NAME = "kafka"
KAFKA_SERVICE_NAME = "kafka"
PRODUCER_SERVICE_NAME = "Spark->Kafka Producer"
KERBEROS_FLAG = "false"
JAR_URI = "https://s3-us-west-2.amazonaws.com/infinity-artifacts/soak/spark/dcos-spark-scala-tests-assembly-0.1-SNAPSHOT.jar"


def run_pipeline(stop_count, spark_app_name):
    broker_dns = _kafka_broker_dns()
    topic = "top-{}".format(spark_app_name)

    # arguments to the application
    common_args = [
        "--conf", "spark.scheduler.maxRegisteredResourcesWaitingTime=2400s",
        "--conf", "spark.scheduler.minRegisteredResourcesRatio=1.0",
        "--conf", "spark.mesos.containerizer=mesos",
        "--conf", "spark.mesos.executor.docker.image=mesosphere/spark-dev:931ca56273af913d103718376e2fbc04be7cbde0",
        "--conf", "spark.mesos.uris=http://norvig.com/big.txt"
    ]

    submit_producer(broker_dns, common_args, topic, spark_app_name)

    submit_consumers(broker_dns, common_args, topic, spark_app_name, str(stop_count))


def submit_producer(broker_dns, args, topic, spark_app_name):
    big_file = "file:///mnt/mesos/sandbox/big.txt"

    producer_args = " ".join([broker_dns, big_file, topic, KERBEROS_FLAG])

    print("producer_args: {}".format(producer_args))

    producer_config = ["--conf", "spark.cores.max=2",
                       "--conf", "spark.executor.cores=2",
                       "--class", "KafkaFeeder"] + args

    producer_id = utils.submit_job(app_url=JAR_URI,
                                   app_args=producer_args,
                                   app_name=spark_app_name,
                                   args=producer_config,
                                   verbose=False)
    return producer_id


def submit_consumers(broker_dns, args, topic, spark_app_name, stop_count):
    consumer_args = " ".join([broker_dns, topic, stop_count, KERBEROS_FLAG])

    consumer_config = ["--conf", "spark.cores.max=4",
                       "--class", "KafkaConsumer"] + args

    for i in range(0, 10):
        utils.submit_job(app_url=JAR_URI,
                         app_args=consumer_args,
                         app_name=spark_app_name,
                         args=consumer_config,
                         verbose=False)


def _kafka_broker_dns():
    cmd = "{package_name} --name={service_name} endpoints broker".format(
        package_name=KAFKA_PACKAGE_NAME,
        service_name=KAFKA_SERVICE_NAME)
    rt, stdout, _ = sdk_cmd.run_raw_cli(cmd)
    assert rt == 0, "Failed to get broker endpoints"
    return json.loads(stdout)["dns"][0]


if __name__ == "__main__":
    usage = """
        Setup: export PYTHONPATH=../spark-testing:../testing:../tests
        Usage: python streaming_test.py [dispatcher_file] 
    """

    if len(sys.argv) < 2:
        print(usage)
        sys.exit(2)

    dispatchers_file = sys.argv[1]
    print("dispatchers_file: {}".format(dispatchers_file))
    with open(dispatchers_file) as f:
        dispatchers = f.read().splitlines()
    print("dispatchers: {}".format(dispatchers))

    print("Installing kafka CLI...")
    rc, stdout, stderr = sdk_cmd.run_raw_cli("package install {} --yes --cli".format(KAFKA_PACKAGE_NAME))

    for dispatcher in dispatchers:
        run_pipeline(stop_count=20,
                     spark_app_name=dispatcher)


    # launch_rate_per_min = int(sys.argv[2])
    # print("launch_rate_per_min: {}".format(launch_rate_per_min))
    #
    # submit_loop(launch_rate_per_min, dispatchers)
