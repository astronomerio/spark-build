import scala.util.Random

import org.apache.spark.internal.Logging
import org.apache.spark.storage.StorageLevel
import org.apache.spark.streaming.receiver.Receiver

class RandomWordReceiver(wordsPerSecond: Float) extends Receiver[String](StorageLevel.MEMORY_ONLY_2) with Logging {

  val waitFor : Long = (1000L / wordsPerSecond).toLong
  val inputList : Array[String] = "the quick brown fox jumps over the lazy dog".split(" ")

  val random : Random = Random


  def onStart(): Unit = {
    // Start the thread that receives data over a connection
    new Thread("Random Word Receiver") {
      override def run() : Unit = { receive() }
    }.start()
  }

  def onStop() : Unit = {
    // There is nothing much to do as the thread calling receive()
    // is designed to stop by itself if isStopped() returns false
  }

  /**
    * Select a random word from the input list until the receiver is stopped.
    */
  private def receive(): Unit = {
    try {
      while(!isStopped) {
        val word : String = inputList(random.nextInt(inputList.length))

        logInfo(s"Writing: $word")
        store(word)
        Thread.sleep(waitFor)
      }

      // Restart in an attempt to connect again when server is active again
      restart("Trying to connect again")
    } catch {
      case t: Throwable =>
        // restart if there is any other error
        restart("Error receiving data", t)
    }
  }

}
