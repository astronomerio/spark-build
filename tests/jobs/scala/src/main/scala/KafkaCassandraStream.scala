import java.util.Properties
import java.util.UUID.randomUUID

import com.datastax.spark.connector.cql.CassandraConnector
import org.apache.kafka.clients.producer.{KafkaProducer, ProducerConfig, ProducerRecord}
import org.apache.spark.mllib.random.RandomRDDs.normalRDD
import org.apache.spark.sql.SparkSession
import org.apache.spark.streaming.dstream.ConstantInputDStream
import org.apache.spark.streaming.{Seconds, StreamingContext}
import scopt.OptionParser

import scala.math.max
import scala.util.Random

import com.datastax.spark.connector._


case class Employee(
                     id: String,
                     first_name: String,
                     last_name: String,
                     email_address: String,
                     address: String,
                     city: String
                   )

/**
  * Application that generates random records and streams them to Cassandra.
  *
  * Usage:
  * {SPARK} {ARGS} {PATH_TO_ASSEMBLY}
  * where {SPARK} is either `dcos spark run` or `./bin/spark-submit`
  * {ARGS} are the configuration arguments to Spark.
  * {PATH_TO_ASSEMBLY} is the location of the snapshot jar containing this application
  *
  * Example:
  * dcos spark run --submit-args='\
  * --conf spark.cassandra.connection.host=node-0-server.cassandra.autoip.dcos.thisdcos.directory \
  * --conf spark.cassandra.connection.port=9042 \
  * --conf spark.mesos.executor.docker.image=mesosphere/spark:latest \
  * --conf spark.mesos.executor.home=/opt/spark/dist \
  * --class KafkaCassandraStream \
  * http://infinity-artifacts.s3.amazonaws.com/autodelete7d/dcos-spark-scala-tests-assembly-0.1-SNAPSHOT.jar \
  * --numberOfRecords 100000 --numberOfPartitions 10 --minColumnsLength 20 --maxColumnsLength 30'
  */
object KafkaCassandraStream {
  def randomString(minLength: Int, maxLength: Int): String =
    Random.alphanumeric.take(max(minLength, Random.nextInt(maxLength))).mkString("")

  def randomUuid(): String =
    randomUUID.toString

  def randomEmployee(minColumnsLength: Int, maxColumnsLength: Int): Employee =
    Employee(
      randomUuid(),
      randomString(minColumnsLength, maxColumnsLength),
      randomString(minColumnsLength, maxColumnsLength),
      randomString(minColumnsLength, maxColumnsLength),
      randomString(minColumnsLength, maxColumnsLength),
      randomString(minColumnsLength, maxColumnsLength)
    )

  def main(args: Array[String]): Unit = {
    object config {
      var numberOfRecords: Long = 100000L
      var numberOfPartitions: Int = 10
      var minColumnsLength: Int = 20
      var maxColumnsLength: Int = 30
    }

    val parser = new OptionParser[Unit]("Kafka Cassandra Stream") {
      opt[Long]("numberOfRecords").action((x, _) => config.numberOfRecords = x)
      opt[Int]("numberOfPartitions").action((x, _) => config.numberOfPartitions = x)
      opt[Int]("minColumnsLength").action((x, _) => config.minColumnsLength = x)
      opt[Int]("maxColumnsLength").action((x, _) => config.maxColumnsLength = x)
    }

    if (!parser.parse(args)) {
      println("Error: Bad arguments")
      System.exit(1)
    } else {
      val numberOfRecords = config.numberOfRecords
      val numberOfPartitions = config.numberOfPartitions
      val minColumnsLength = config.minColumnsLength
      val maxColumnsLength = config.maxColumnsLength

      val spark = SparkSession
        .builder()
        .appName("Kafka Cassandra Stream")
        .getOrCreate()

      val streamingContext = new StreamingContext(spark.sparkContext, Seconds(2))
      val cassandra = CassandraConnector(spark.sparkContext.getConf)
      val keyspaceName = "kafka_cassandra_stream"
      val tableName = "records"

      cassandra.withSessionDo { session =>
        session.execute(s"""DROP KEYSPACE IF EXISTS $keyspaceName""")
        session.execute(
          s"""CREATE KEYSPACE $keyspaceName WITH REPLICATION = {
          'class': 'SimpleStrategy',
          'replication_factor': 3
        }""")
        session.execute(
          s"""
          CREATE TABLE IF NOT EXISTS $keyspaceName.$tableName (
            id uuid PRIMARY KEY,
            first_name text,
            last_name text,
            email_address text,
            address text,
            city text
          );"""
        )
      }

      val recordsRdd = normalRDD(spark.sparkContext, numberOfRecords, numberOfPartitions).map(_ => randomEmployee(minColumnsLength, maxColumnsLength))
      // TODO: input stream source should be Kafka.
      val recordsStream = new ConstantInputDStream(streamingContext, recordsRdd)
      val employeeColumns = SomeColumns("id", "first_name", "last_name", "email_address", "address", "city")

      recordsStream.foreachRDD { rdd =>
        println(s"Writing batch of size ${rdd.count} to Cassandra...")
        val t0 = System.nanoTime()
        rdd.saveToCassandra(keyspaceName, tableName, employeeColumns)
        val t1 = System.nanoTime()
        println(s"Wrote batch in ${(t1 - t0) / 1000 / 1000} ms")

        // TODO: remove this when not using ConstantInputDStream anymore.
        streamingContext.stop() // we only need to go through the ConstantInputDStream once.
      }

      streamingContext.start()
      streamingContext.awaitTermination()
    }
  }
}


object KafkaRandomFeeder {
  def main(args: Array[String]): Unit = {

    val config : Config = Config()

    if (!getParser("KafkaRandomFeeder").parse(args, config).isDefined) {
      println("Error: Bad arguments")
      System.exit(1)
    }

    val sparkBuilder = SparkSession.builder().appName(config.appName)


    val spark = sparkBuilder
      .master("local[2]")
      .getOrCreate()

    val streamingContext = new StreamingContext(spark.sparkContext, Seconds(config.batchSizeSeconds))

    val wordsPerSecond = config.wordsPerSecond
    val stream = streamingContext.receiverStream(new RandomWordReceiver(wordsPerSecond))


    val kafkaProperties = getKafkaProperties(config.brokers, config.kerberized)
    val topic : String = config.topic

    stream.foreachRDD { rdd =>
      rdd.foreachPartition { p =>

        val producer = new KafkaProducer[String, String](kafkaProperties)
        p.foreach { r =>
          println(s"Writing ${r} to Kafka")
          val msg = new ProducerRecord[String, String](topic, null, r)
          producer.send(msg)
        }
        producer.close()

      }
    }

    streamingContext.start()
    streamingContext.awaitTermination()
  }


  def getKafkaProperties(brokers : String, kerberized: Boolean) : Properties = {

    val props = new Properties()
    props.put(ProducerConfig.BOOTSTRAP_SERVERS_CONFIG, brokers)
    props.put(ProducerConfig.VALUE_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringSerializer")
    props.put(ProducerConfig.KEY_SERIALIZER_CLASS_CONFIG, "org.apache.kafka.common.serialization.StringSerializer")
    if (kerberized) {
      props.put("sasl.kerberos.service.name", "kafka")
      props.put("security.protocol", "SASL_PLAINTEXT")
      props.put("sasl.mechanism", "GSSAPI")
    }

    return props
  }


  case class Config(
                     appName: String = "KafkaRandomFeeder",
                     brokers: String = "" ,
                     topic: String = "",
                     kerberized: Boolean = false,
                     wordsPerSecond: Float = 1.0F,
                     batchSizeSeconds: Int = 1
                   )


  def getParser(programName : String) : scopt.OptionParser[Config] = {

    val parser = new scopt.OptionParser[Config](programName) {

      opt[String]("appName").action( (x, c) =>
      c.copy(appName = x) ).text("The application name to use for the Spark streaming app")

      opt[String]("brokers").required().action( (x, c) =>
      c.copy(brokers = x) ).text("The broker connection information")

      opt[String]("topic").action( (x, c) =>
      c.copy(topic = x) ).text("The topic to write to")

      opt[Unit]('k', "kerberized").action( (_, c) =>
      c.copy(kerberized = true) ).text("Enable Kerberized mode")

      opt[Double]("wordsPerSecond").action( (x, c) =>
      c.copy(wordsPerSecond = x.toFloat) ).text("The rate at which words should be used to Kafka")

      opt[Int]("batchSizeSeconds").action( (x, c) =>
      c.copy(batchSizeSeconds = x) ).text("The window size to be used for the Spark streaming batch")

    }

    return parser
  }

}

