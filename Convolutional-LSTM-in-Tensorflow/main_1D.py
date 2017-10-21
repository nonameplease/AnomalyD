from __future__ import print_function
import os.path
import time

import numpy as np
import tensorflow as tf
#import cv2
from fits_reader import *
import bouncing_balls as b
import layer_def as ld
from ConvLSTM1D import BasicConvLSTMCell

FLAGS = tf.app.flags.FLAGS

tf.app.flags.DEFINE_string('train_dir', './checkpoints/train_store_conv_lstm',
                            """dir to store trained net""")
tf.app.flags.DEFINE_string('data_dir', './Data',
                            """dir to load data""")
tf.app.flags.DEFINE_integer('seq_length', 16,
                            """size of hidden layer""")
tf.app.flags.DEFINE_integer('seq_start', 5,
                            """ start of seq generation""")
tf.app.flags.DEFINE_integer('max_step', 200000,
                            """max num of steps""")
tf.app.flags.DEFINE_float('keep_prob', .8,
                            """for dropout""")
tf.app.flags.DEFINE_float('lr', .001,
                            """for dropout""")
tf.app.flags.DEFINE_integer('batch_size', 16,
                            """batch size for training""")
tf.app.flags.DEFINE_float('weight_init', .1,
                            """weight init for fully connected layers""")

#fourcc = cv2.cv.CV_FOURCC('m', 'p', '4', 'v') 

def generate_bouncing_ball_sample(batch_size, seq_length, shape, num_balls):
  dat = np.zeros((batch_size, seq_length, shape, shape, 3))
  for i in xrange(batch_size):
    dat[i, :, :, :, :] = b.bounce_vec(32, num_balls, seq_length)
  return dat 
def encode_stack(inputs, i):
  conv1 = ld.conv_layer_1D(inputs, 3, 2, 8, "encode_{}".format(i+1))
  # conv2
  conv2 = ld.conv_layer_1D(conv1, 3, 1, 8, "encode_{}".format(i+2))
  return conv2

def decode_stack(inputs, i):
  conv1 = ld.transpose_conv_layer_1D(inputs, 3, 2, 8, "decode_{}".format(i+1))
  # conv2
  conv2 = ld.transpose_conv_layer_1D(conv1, 3, 1, 8, "decode_{}".format(i+2))
  return conv2

def network(inputs, hidden, lstm=True):
  #inputs is 3D tensor (batch, )
  conv1 = ld.conv_layer_1D(inputs, 5, 2, 8, "encode_1")
  # conv2
  conv = ld.conv_layer_1D(conv1, 3, 1, 8, "encode_2")
  for i in xrange(2,10,2):
    conv = encode_stack(conv, i)

  conv = ld.conv_layer_1D(conv, 1, 1, 4, "encode_{}".format(i+3))
  y_0 = conv
  
  if lstm:
    # conv lstm cell 
    with tf.variable_scope('conv_lstm', initializer = tf.random_uniform_initializer(-.01, 0.1)):
      cell = BasicConvLSTMCell([16,], [5,], 4)
      if hidden is None:
        hidden = cell.zero_state(FLAGS.batch_size, tf.float32) 
      y_1, hidden = cell(y_0, hidden)
  else:
    y_1 = ld.conv_layer_1D(y_0, 3, 1, 8, "encode_{}".format(i+4))
  #import IPython; IPython.embed()
  dconv = ld.transpose_conv_layer_1D(y_1, 1, 1, 8, "decode_1")
  for i in xrange(1,9,2):
    dconv = decode_stack(dconv, i)
  # x_1 
  x_1 = ld.transpose_conv_layer_1D(dconv, 5, 2, 1, "decode_{}".format(i+3), True) # set activation to linear

  return x_1, hidden

# make a template for reuse
network_template = tf.make_template('network', network)

def train():
  """Train ring_net for a number of steps."""
  with tf.Graph().as_default():
    # make inputs
    x = tf.placeholder(tf.float32, [None, FLAGS.seq_length, 512, 1])

    # possible dropout inside
    keep_prob = tf.placeholder("float")
    x_dropout = tf.nn.dropout(x, keep_prob)

    # create network
    x_unwrap = []

    # conv network
    hidden = None
    for i in xrange(FLAGS.seq_length-1):
      if i < FLAGS.seq_start:
        x_1, hidden = network_template(x_dropout[:,i,:,:], hidden)
      else: #conditional generation
        x_1, hidden = network_template(x_1, hidden)
      x_unwrap.append(x_1)

    # pack them all together 
    x_unwrap = tf.stack(x_unwrap)
    x_unwrap = tf.transpose(x_unwrap, [1,0,2,3])

    # this part will be used for generating video
    x_unwrap_g = []
    hidden_g = None
    for i in xrange(32):
      if i < FLAGS.seq_start:
        x_1_g, hidden_g = network_template(x_dropout[:,i,:,:], hidden_g)
      else:  #conditional generation
        x_1_g, hidden_g = network_template(x_1_g, hidden_g)
      x_unwrap_g.append(x_1_g)

    # pack them generated ones
    x_unwrap_g = tf.stack(x_unwrap_g)
    x_unwrap_g = tf.transpose(x_unwrap_g, [1,0,2,3])

    # calc total loss (compare x_t to x_t+1)
    loss = tf.nn.l2_loss(x[:,FLAGS.seq_start+1:,:,:] - x_unwrap[:,FLAGS.seq_start:,:,:])
    tf.summary.scalar('loss', loss)

    # training
    train_op = tf.train.AdamOptimizer(FLAGS.lr).minimize(loss)
    
    # List of all Variables
    variables = tf.global_variables()

    # Build a saver
    saver = tf.train.Saver(tf.global_variables())   

    # Summary op
    summary_op = tf.summary.merge_all()
 
    # Build an initialization operation to run below.
    init = tf.global_variables_initializer()

    # Start running operations on the Graph.
    sess = tf.Session()

    # init if this is the very time training
    print("init network from scratch")
    sess.run(init)

    # Summary op
    graph_def = sess.graph.as_graph_def(add_shapes=True)
    summary_writer = tf.summary.FileWriter(FLAGS.train_dir, graph_def=graph_def)
    files = find_files(FLAGS.data_dir)
    sample_dir = FLAGS.data_dir + '/samples/'
    if not os.path.exists(sample_dir):
      os.makedirs(sample_dir)
    for step in xrange(FLAGS.max_step):
      #dat = generate_bouncing_ball_sample(FLAGS.batch_size, FLAGS.seq_length, 32, FLAGS.num_balls)
      dat = load_batch(FLAGS.batch_size, files, step)
      t = time.time()
      _, loss_r = sess.run([train_op, loss],feed_dict={x:dat, keep_prob:FLAGS.keep_prob})
      elapsed = time.time() - t

      if step%100 == 0 and step != 0:
        summary_str = sess.run(summary_op, feed_dict={x:dat, keep_prob:FLAGS.keep_prob})
        summary_writer.add_summary(summary_str, step) 
        print("time per batch is " + str(elapsed))
        print(step)
        print(loss_r)
      
      assert not np.isnan(loss_r), 'Model diverged with loss = NaN'

      if step%1000 == 0:
        checkpoint_path = os.path.join(FLAGS.train_dir, 'model.ckpt')
        saver.save(sess, checkpoint_path, global_step=step)  
        print("saved to " + FLAGS.train_dir)

        # make video
        print("now saving sample!")
        dat_gif = dat
        ims = sess.run([x_unwrap_g],feed_dict={x:dat_gif, keep_prob:FLAGS.keep_prob})
        ims = ims[0].squeeze()
        print(ims.shape)
        plt.imshow(ims, aspect='auto')
        plt.savefig(sample_dir+'step_{}.png'.format(step))


def main(argv=None):  # pylint: disable=unused-argument
  if tf.gfile.Exists(FLAGS.train_dir):
    tf.gfile.DeleteRecursively(FLAGS.train_dir)
  tf.gfile.MakeDirs(FLAGS.train_dir)
  train()

if __name__ == '__main__':
  tf.app.run()

