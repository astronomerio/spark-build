# Spark Scale Tests

## Batch
[To be filled in]

## Streaming
To run the Kafka-Spark Streaming word count app:
- Install kafka
  ```bash
  dcos package install kafka --yes
  ```
- Deploy spark dispatchers
  ```bash
  Usage: deploy-dispatchers.py [options] [num_dispatchers] <num_dispatchers> <service_name_base> <output_file>
  ```
  Example:
  ```bash
  python deploy-dispatchers.py 10 spark-streaming dispatchers.out 
  ```
- Run spark streaming scale test
  ```bash
  Setup: export PYTHONPATH=../spark-testing:../testing:../tests
  Usage: python streaming_test.py <dispatcher_file> <num_consumers_per_producer> <desired_runtime_in_mins>
  ```
  Example:
  ```bash
  export PYTHONPATH=../spark-testing:../testing:../tests
  python streaming_test.py dispatchers.out 10 10
  ```
  - This will create 1 topic, 1 producer, and 10 consumers per dispatcher. 
  - The `desired_runtime_in_mins` is a rough estimate on when the very last consumer will complete (there is some startup overhead).
- When all consumers have finished, uninstall the dispatchers. This will in turn, shutdown all associated drivers including producers.
  ```bash
  ./uninstall_dispatcher.sh dispatchers.out
  ```