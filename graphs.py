import time
import datetime

from optoConn.tools import *
from optoConn       import optoConnMain as ACM
from IPython        import display
from numpy.random   import randint

import numpy             as np
import matplotlib.pyplot as plt
import tensorflow        as tf
#import matplotlib.animation as anim

from tensorflow.python.ops             import rnn, rnn_cell
from tensorflow.python.ops             import variable_scope        as vs
from tensorflow.python.ops.constant_op import constant  as const


'''
    _________________________________________________________________________

                                 MODELS DESCRIPTION
    _________________________________________________________________________


    '__classOptoNN__'  :
            All to all neural network with a classifer (logistic) as output layer
            that tries to predicted if there was an otpogenetic stimulation in 
            a neuron j. Input will be time serie of neuron(s) i starting at time t 
            and output will be a binary value, where the label is whether x was 
            stimulated or not at t-z. 


    '__classOptoRNN__' :

            Reccurent neural network with a classifer (logistic) as output layer
            that tries to predicted if there was an otpogenetic stimulation in 
            a neuron j. Input will be time serie of neuron(s) i starting at time t 
            and output will be a binary value, where the label is whether x was 
            stimulated or not at t-z. 

    '__NAR__'      :

            Non linear regressive model that predicts the calcium activity at t+i
            based on the activity of the recorded population. 



    '__NGCmodel__' : 

            UNDER DEVELOPMENT

            Reccurent neural network with calcium dynamic model that predicts the 
            calcium activity at t+i based on the activity of the recorded population. 

            The model is composed of two parts :
           
                    RNN(Network & Globalcell) + Calcium dynamics

                    1. RNN( The global & network cell )
                        
                      The 'global' cells is a low rank RNN with the goal 
                      of capturing global dynamics (fast and slow). 

                      The 'network' cells try to capture the real dynamic 
                      and connectivity between the units observed in 
                      the data.
                    
                    2. F( Calcium dynamic + 1. ) 
                        
                      Calcium dynamic integrates previous cell 
                      and is also influenced by the previous 
                      inputstep with calcium decay.

    _________________________________________________________________________

                                      FUNCTIONS
    _________________________________________________________________________

    batchCreation : Creates batches for training.

    _cost         : Will calculate the cost depending on the model used.

    _masking      : Adding masks in the tensorflow graph that will 
                    be applied to the designed weights after every
                    variables update.
    
    _VNoise       : Adding stochasticity in all the tensorflow graph 
                    variables after every update for a stotastic 
                    gradient descent. CURRENTLY NOT USED. See masks for
                    current implementation.
    
    launchGraph   : Will lauch the training of the model

    showVars      : Will plot the variables with imshow (matrices)
                    and plot (vectors)

    plotfit       : Will plot the test set and the prediction of 
                    the model. To use for the non-classification model
                    that predict the time series. 

    _________________________________________________________________________

                                       MASKING
    _________________________________________________________________________


    Masks are used to modulate the parameter space that can be
    explored by the model. They are applied after every variable
    update.
     The first character of a mask has a meaning :
    
                       0 : Mask replace the respective weight
                       1 : Mask is added to the respective weight
                       2 : Mask is multipled with the respective weight
                       
    
     Mask operations will be executed in the same order
     '_M' should be added at the end of the name if the name in the weights 
     dictionnary would be identical otherwise. '_W' can be added to the 
     corresponding name variable instead of '_M' to distinguish them more
     easily.

     ________________________________________________________________________

'''   


class actConnGraph(object):
    # Default graph for Active Connectonic uncovering

    '''
    ________________________________________________________________________

                                     ARGUMENTS
    ________________________________________________________________________
 
    
    featDict: Dictionnary that contains the parameters used to 
              build the graph. To see a list of the parameters,
              see optoConnMain.py file. 

    ________________________________________________________________________

    '''

    def __init__(self, featDict ):

  
        #Assigining attributes from featDict
        for key, val in featDict.items():
                setattr(self, key, val)

        #Saving dictionnary
        self._pDict = featDict

        #Specifying model
        model = getattr(self, self.model)

        # ---------------------------------------- GRAPH ----------------------------------------- #
        graph = tf.Graph()
        with graph.as_default():    

            #Variable placeholders  

            if 'class' in self.model:
                self._Y = tf.placeholder("float32", [None,1], name = 'Y')
                self._X = tf.placeholder("float32", [None, self.seqLen], name = 'X') 
                self._keepProb =  tf.placeholder("float32", [] , name = 'keepProb') 
            else:
                self._Y = tf.placeholder("float32", [None, self.nInput], name = 'Y')
                self._X = tf.placeholder("float32", [None, self.seqLen, self.nInput], 
                                         name = 'X') 
                        
            self._batch     = tf.placeholder("int32", [], name = 'batch')
            self._batchSize = tf.placeholder("int32",[],  name = 'batchSize')                                               

            #Learning rate decay 
            self._currLR = tf.train.exponential_decay(self.learnRate, #LR intial value
                                            self._batch,         #Current batch
                                            200,                 #Decay step
                                            0.90,                #Decay rate
                                            staircase = True)

            #Shape data
            if not 'class' in self.model: 
              _Z1 = shapeData(self._X, self.seqLen, self.nInput)
              #Prediction using models
              self._Z2 = model(_Z1)
            else:
              self._Z2 = model(self._X)


            #List of all variables 
            self.variables = tf.trainable_variables() 		

            #Variables assigned to each of the variable name 
            self.vnames = {v.name:v for v in self.variables} 

            #Cost function
            cost = self._cost()

            #Gradients
            self._grad = {var.name: tf.gradients(cost, var) for var in self.variables}

            #Model label prediction
            self._resp = self._classiPred()

            #To test the precision of the network
            self.precision = tf.reduce_mean(tf.pow(self._Z2 - self._Y, 2))
 
            #Backpropagation
            self.optimizer = tf.train.AdamOptimizer( learning_rate = 
                                                     self._currLR ).minimize(cost)

            #Adding gaussian noise to variables updates
            #self.V_add_noise = self._VNoise(self.variables) # List of var.assign_add(noise) for all variables

            #Applying masking for restained connectivity
            self.masking = self._masking()

            #Saving graph
            self.saver = tf.train.Saver()


        self.graph = graph


    '''
        ________________________________________________________________________

                                         MODELS
        ________________________________________________________________________
     
    '''

    def __classOptoRNN__(self,_Z1):

        ''' Reccurent neural network with a classifer (logistic) as output layer
            that tries to predicted if there was an otpogenetic stimulation in 
            a neuron j. Input will be time serie of neuron(s) i starting at time t 
            and output will be a binary value, where the label is whether x was 
            stimulated or not at t-z. 


        '''

                #Defining weights
        self.weights = { 
                         'classi_HO_W' : varInit([self.nhidclassi,1],
                                                  'classi_HO_W', std = 0.01 )
                        }

        self.biases  = { 'classi_HO_B': varInit([1], 'classi_HO_B',
                                                std = 1) } 

        self.masks   = { }


        #classiCell = rnn_cell.BasicLSTMCell(self.nhidclassi)
        classiCell = rnn_cell.BasicRNNCell(self.nhidclassi, activation = self.actfct)
        #classiCell = rnn_cell.GRUCell(self.nhidclassi, activation = self.actfct)

        #INITIAL STATE DOES NOT WORK
        #initClassi = tf.zeros([self.batchSize,classiCell.state_size], dtype='float32') 

        if self.multiLayer:
            #Stacking classifier cells
            stackCell = rnn_cell.MultiRNNCell([classiCell] * self.multiLayer)
            S = stackCell.zero_state(self._batchSize, tf.float32)
            with tf.variable_scope("") as scope:
                for i in range(self.seqLen):
                    if i == 1:
                        scope.reuse_variables()
                    O,S = stackCell(_Z1,S)

            predCell = tf.matmul(O, self.weights['classi_HO_W'])  + \
                       self.biases['classi_HO_B']

        else:
            #classi
            O, S = rnn.rnn(classiCell, _Z1, dtype = tf.float32) #Output and state

            #classi to output layer
            predCell = tf.matmul(O[-1], self.weights['classi_HO_W'])  + \
                       self.biases['classi_HO_B']

        return predCell

        #Network prediction


    def __classOptoNN__(self,_Z1):

        ''' All to all neural network with a classifer (logistic) as output layer
            that tries to predicted if there was an otpogenetic stimulation in 
            a neuron j. Input will be time serie of neuron(s) i starting at time t 
            and output will be a binary value, where the label is whether x was 
            stimulated or not at t-z. 


        '''

                #Defining weights

        #Creating weight matrices 
        self.weights = {   l: varInit([self.nhidclassi]*2, 'hidW'+str(l),
                                       ortho = False, std = 0.01 ) 
                                       for l in range(self.multiLayer)   }
        self.weights      ['in']  = varInit( [self.seqLen,self.nhidclassi],'inW',
                                       ortho = False, std = 0.01 )
        self.weights['out'] = varInit( [self.nhidclassi,1],'outW', 
                                       ortho = False, std = 0.01 )
                                
        #Creating biases
        self.biases  = {  l: varInit([self.nhidclassi],'bias'+str(l))
                             for l in range(self.multiLayer) } 
        self.biases['in']  = varInit([self.nhidclassi],'inB')
        self.biases['out'] = varInit([1],'outB')

        self.masks   = { }

        #Input layer
        H = tf.add( tf.matmul( _Z1,self. weights['in'] ), self.biases['in'] )
        H = self.actfct(H)

        #Hidden layers
        for l in range(self.multiLayer):
            H = tf.add( tf.matmul( H, self.weights[l] ), self.biases[l] )
            H = tf.nn.dropout(H, self._keepProb) #Dropout
            H = self.actfct(H)

        #Output layer
        pred = tf.matmul(H,self.weights['out']) + self.biases['out']

        return pred

        #Network prediction

    def __NAR__(self,_Z1):
      ''' Non Linear Regressive model used to infer the connectivity '''

      self.weights = { 'NAR_W': varInit([self.nInput]*2, 'NAR_W', std = 0.001) }
      self.biases  = { 'NAR_B': varInit([self.nInput],   'NAR_B', std = 0.001) }
      self.masks   = { '1NAR_M': tf.random_normal([self.nInput]*2, 
                                                  .001) * self._currLR }
      #self.masks = {}

      #Non-linear
      Z2 = self.actfct( tf.matmul(_Z1[-1], self.weights['NAR_W']) + self.biases['NAR_B'] )
      
      #Linear
      #Z2 = ( tf.matmul(_Z1[-1], self.weights['NAR_W']) ) #  + self.biases['NAR_B'] )

      return Z2


    def __NGCmodel__(self,_Z1):
        ''' RNN(Network+Global cells) & Calcium dynamic

            Define weights & masks

                ng_H0_W  : Network&Global hidden -> output (HO)

                alpha    : Decay of data input at t-1
                             0alpha_M: Contrains values between 0 and 1

                ng_IH_HH : Network&Global cell Input  -> Hidden (IH) & Hidden -> Hidden (HH) 
                             
                             1ng_IH_HH: 
                                Mask will be applied so that netw cell receives input from 
                                glob and data, but glob cell only receive data. Furthermore,
                                network cell self-connectivity is prevented by putting the
                                identity to 0. 

                             2ng_IH_HH:
                                Noise is added to this weight matrix for bayesian learning.
                
        '''

        #Total number of hidden units
        nhid = self.nhidNetw + self.nhidGlob

        #Defining weights
        self.weights = { 
                         'ng_H0_W' : varInit([nhid,self.nOut], 'ng_HO_W' ), 
                         'alpha_W' : varInit([self.nInput,1],  'alpha_W' ),
                        }

        #Defining masks
        self.masks = {
                       '1ng_IH_HH': 
                          np.vstack([ 
                                     np.ones([self.nInput, nhid],  dtype='float32'),
                                     np.hstack([ np.ones( [self.nhidNetw]*2,       dtype='float32')   
                                          -np.identity(self.nhidNetw,              dtype='float32'),
                                           np.zeros([self.nhidNetw,self.nhidGlob], dtype='float32') ]),
                                     np.ones([self.nhidGlob,nhid], dtype='float32')
                                    ]),

                       '2ng_IH_HH': tf.random_normal([self.nInput + nhid, nhid],
                                                    0.001) * self.learnRate/2,
                       '0alpha_M' : tf.clip_by_value(self.weights['alpha_W'],0,1)
                      } 

        #Defining biases
        self.biases = { 'ng_H0_B' : varInit(self.nOut, 'ng_H0_B') }  

        #Noise distribution parameters
        ng_Gmean = varInit([1],'ng_Gmean')
        ng_Gstd  = varInit([1],'ng_Gstd' )

        #Network + Global dynamic cell (concatenated)
        ngCell  = rnn_cell.BasicRNNCell(nhid, activation= self.actfct)
        ngCellS = rnn_cell.MultiRNNCell([ngCell])

        #Initialization
        ngO = ngCellS.zero_state(self.batchSize,tf.float32) #Netw+Glob state initialization 
        Z2  = tf.zeros(1)                                   #Model prediction

        #RNN looping through sequence time points
        with tf.variable_scope("ng_IH_HH") as scope:
            for i in range(self.seqLen):

                #Reusing variables for RNN
                if i == 1:
                  scope.reuse_variables()

                #Prediction error for time t
                ZD = _Z1[i] - Z2

                #Network + global cell
                ngO, ngS = ngCellS(ZD, ngO)

                #NG to output cells 
                #ng_Z2 = tf.tanh(tf.matmul(ngO, self.weights['ng_H0_W'] + self.biases['ng_H0_B']))
                ng_Z2 = ngO[:,:self.nhidNetw]

                #Gaussian noise
                gNoise = tf.random_normal([self.batchSize,self.nOut], mean   = ng_Gmean, 
                                                                      stddev = ng_Gstd,  
                                                                      dtype  = 'float32' )
                gNoise = 0

                #Prediction with calcium dynamic
                #Z2 = tf.tanh(tf.matmul(_Z1[i], self.weights['alpha_W']) + ng_Z2 + gNoise)
                Z2 = tf.tanh(ng_Z2 + gNoise)
        
        return Z2



    '''
    ________________________________________________________________________

                                VARIABLE FUNCTIONS
    ________________________________________________________________________

    '''


    def batchCreation(self, inputs, outputs, nbIters=100, perm = True):
        ''' 
        ________________________________________________________________________

                                       ARGUMENTS
        ________________________________________________________________________


        inputs    : Input data sequence (time series fed into model)
        outputs   : Output data (label or prediction)
        nbIters   : Number of batches per batchcreation
        perm      : Wheter batches will be selected via permutation (no replacement)
                    or random.


        ________________________________________________________________________

                                     RETURNS
        ________________________________________________________________________


        Y1 : Batches inputs  (nBatches x batchSize x nInput)
        Y2 : Batches outputs (nBatches x batchSize x nInput*)
            *nInput is currently only present in non classifier models

      ________________________________________________________________________
_______
 


        '''
        if 'class' in self.model: 
            #If model is a classifier
            nSeq = inputs.shape[1]
        else:
            nSeq = inputs.shape[1] - self.seqLen

        if perm:
            # Will sample sequences with permutation, which will avoid sampling the same
            # sample multiple times in the same batch
            nSeqB  = nbIters*self.batchSize #Total number of sequences for all batches


            #Shuffling sequences
            if nSeqB == nSeq:
                perms = np.random.permutation(nSeq) 
                Y1 =  inputs[:,perms,:]
                Y2 = outputs[perms,:]

            elif nSeqB > nSeq:
                nLoop = np.floor(nSeqB/nSeq) #Number of time go through all sequences
                for i in np.arange(nLoop):
                    perms = np.random.permutation(nSeq)
                    if not i:
                        Y1 =  inputs[:,perms,:]
                        Y2 = outputs[perms,...]
                    else:
                        Y1 = np.hstack((Y1, inputs[:,perms,:]))

                        if len(Y2.shape) == 1:#If classi models, Output is 1D
                            Y2 = np.hstack((Y2,outputs[perms,...]))
                        else:
                            Y2 = np.vstack((Y2,outputs[perms,...]))

                #Residuals
                if nSeqB%nSeq > 0:
                    perms = np.random.permutation(nSeq)

                    Y1 = np.hstack((Y1, inputs[:,perms[np.arange(nSeqB%nSeq)],:]))
                    
                    if len(Y2.shape) == 1: #If classi models, Output is 1D
                        Y2 = np.hstack((Y2,outputs[perms[np.arange(nSeqB%nSeq)],...]))
                    else:
                        Y2 = np.vstack((Y2,outputs[perms[np.arange(nSeqB%nSeq)],...]))

            else: 
                perms  = np.random.permutation(nSeq)

                Y1 = inputs[:,perms[np.arange(nSeqB%nSeq)],...]
                Y2 =  outputs[perms[np.arange(nSeqB%nSeq)],...]

        else:

            randidx = np.random.randint(0,nSeq,self.batchSize*nbIters)

            Y1 = inputs[:,randidx,:]
            Y2 =  outputs[randidx,...]

        #Reshapping
        Y1 = Y1.reshape([nbIters,self.batchSize,self.seqLen,self.nInput])
        if 'class' in self.model: #In classi models, output is 1D
            Y2 = Y2.reshape([nbIters,self.batchSize,2])
        else:
            Y2 = Y2.reshape([nbIters,self.batchSize,self.nInput])

        return Y1, Y2


    def _cost(self):
          ''' Will calculate the costs associated with the loss function '''
          
          #Cost for connectivity in the network cell (H->H)
          
          if 'class' in self.model :
             #If model is a classifier

            #Sparsity regularizer
            #L2 loss
            self._sparsC = tf.add_n([tf.nn.l2_loss(v) for v in self.variables]) 

            #L1 loss
            #self._sparsC = tf.add_n([tf.reduce_sum(tf.abs(v)) for v in self.variables])

            #Cross entropy
            ngml = tf.nn.sigmoid_cross_entropy_with_logits(self._Z2, self._Y)
            self._ngml = tf.reduce_sum(ngml)

            #cost = (self._ngml*self.lossW +self._sparsC*self.sparsW) / \
            #       (2*self.batchSize)

            cost = (self._ngml*self.lossW) / (2*self.batchSize)
                   
          else:

            sparsC = tf.add_n([tf.reduce_sum(tf.abs(v)) for v in self.variables]) 
            self._sparsC = sparsC*self.sparsW

            #Sum of square distance
            self._ngml = tf.reduce_sum(tf.pow(self._Z2 - self._Y,2))*self.lossW

            #Prior
            ngprior = 0

            #Total Cost
            cost = (self._ngml + ngprior + self._sparsC ) / (2*self.batchSize)
            #cost = (self._ngml + ngprior ) / (2*self.batchSize)

          return cost


    def _masking(self):
        ''' Will create the operations to update the weights

        The first character of a mask has a meaning :
        
                           0 : Mask replace the respective weight
                           1 : Mask is added to the respective weight
                           2 : Mask is multipled with the respective weight
        
         Mask operations will be executed in the same order '''

        Vars = self.variables.copy()

        #Names of variables
        vnames = [var.name[:-2] for var in Vars]

        #Will hold variables changes
        tempM =  [var.value() for var in Vars] 

        #Which variables will the masks be applied on
        vidxAll = []     

        # Applying masks
        for m in sorted(self.masks):
            if m[1:] in vnames:
                #If mask is present in variables as it is
                vidx = vnames.index(m[1:]) #Index of variable

                if   m[0] == '0':
                    tempM[vidx] = self.masks[m]
                elif m[0] == '1':
                    tempM[vidx] = tf.add(tempM[vidx],self.masks[m])
                elif m[0] == '2':
                    tempM[vidx] = tf.mul(tempM[vidx],self.masks[m])


            elif any([ (m[1:] in var and 'Matrix' in var) for var in vnames]):

                #Name of mask might be part of a variable scope

                for var in vnames:
                    if  (m[1:] in var and 'Matrix' in var):
                        vidx = vnames.index(var) #Index of variable
                if   m[0] == '0':
                    tempM[vidx] = self.masks[m]
                elif m[0] == '1':
                    tempM[vidx] = tf.add(tempM[vidx],self.masks[m])
                elif m[0] == '2':
                    tempM[vidx] = tf.mul(tempM[vidx],self.masks[m])


            elif m[-2:] == '_B' and any([ (m[1:] in var and 'Bias' in var) for var in vnames]):

                #Name of mask might be part of a variable scope

                for var in vnames:
                    if  m[1:] in var and 'Bias' in var and m[-2:] == '_B':
                        vidx = vnames.index(var) #Index of variable
                if   m[0] == '0':
                    tempM[vidx] = self.masks[m]
                elif m[0] == '1':
                    tempM[vidx] = tf.add(tempM[vidx],self.masks[m])
                elif m[0] == '2':
                    tempM[vidx] = tf.mul(tempM[vidx],self.masks[m])



            elif m[1:-1]+'W' in vnames:

                #Last char might be different to prevent confusion
                vidx = vnames.index(m[1:-1]+'W') #Index of variable

                if   m[0] == '0':
                    tempM[vidx] = self.masks[m]
                elif m[0] == '1':
                    tempM[vidx] = tf.add(tempM[vidx],self.masks[m])
                elif m[0] == '2':
                    tempM[vidx] = tf.mul(tempM[vidx],self.masks[m])

            vidxAll.append(vidx) 
            
        vidxAll = np.unique(vidxAll) #One value per var

        return [Vars[i].assign(tempM[i]) for i in vidxAll]


    def _VNoise(self, variables, learningR = .001, std = .001):
        ''' Adding stochasticity in the tensorflow graph variables at every update
           for a stotastic gradient descent.

            variables: list of all variables
            std      : standart deviation for normal distrubution'''

        V = []
        #Adding random noise
        for v in variables:
            V_add = v.assign_add( learningR*
                                  tf.random_normal(
                                  v.get_shape().as_list(), std) )
            V.append(V_add)

        return V


    def launchGraph(self, D, detail = True, savepath = '_.ckpt'):
        # Launch the graph
        #   Arguments ... 
        #       D ~ Has to be a list of 4 elements : Training_X, training_Y
        #                                                    Testing_X , testing_Y.
        # Detail : Will add predictions, testing scores, training scores, accuracy 
        #          gradient in the graph as attributes at every time step. 

        t = time.time() # Current time
        backupPath = '/tmp/backup.ckpt' # Checkpoint backup path

        #Which sequence for classification mini batches

        if 'class' in self.model:
            trIdx  = [ randint( 0, len( D['Ytr'][0] ),
                              [int(self.batchSize/2), self.nbIters] ),
                       randint( 0, len( D['Ytr'][1] ),
                              [int(self.batchSize/2), self.nbIters] ) ]

            teIdx  = [ randint( 0, len( D['Yte'][0] ),
                              [int(self.batchSize/2), self.nbIters] ),
                       randint( 0, len( D['Yte'][1] ), 
                              [int(self.batchSize/2), self.nbIters] ) ] 
        else:
            trIdx   = randint( 0, len(D['Ytr']), [self.batchSize, self.nbIters] )
            teIdx   = randint( 0, len(D['Yte']), [self.batchSize, self.nbIters] ) 

        #Initialize counters
        stepTr  = 0 #Training steps
        stepBat = 0 #Testing steps
        accNum  = 0 #To calculate accuracy over time

        #Initialize holders
        if detail:
            #Storing more information
            self.pred   = [None]*self.nbIters
            self.grad   = [None]*self.nbIters
            self.lossTr = [None]*self.nbIters
            self.lossTe = []
            ansTr       = np.round(np.random.rand(500,2))
            ansTe       = np.round(np.random.rand(500,2))
            self.acc    = []


        #Setting configs for minimum threads (small model)
        config = tf.ConfigProto(device_count={"CPU": 88},
                          inter_op_parallelism_threads=1,
                          intra_op_parallelism_threads=1)


        with tf.Session(graph=self.graph, config = config) as sess:

            #Initializing the variables
            sess.run(tf.initialize_all_variables())

            if self.sampRate > 0:
                samp   = 0                           #Sample
                nbSamp = self.nbIters//self.sampRate #Number of sample

            # Keep training until reach max iterations
            while stepTr < self.nbIters:

                #Train feed dictionnary 
                FD_tr = self._feedDict(D['Xtr'], D['Ytr'], stepTr ,trIdx)

                if detail:
                    #Test feed dictionnary 
                    FD_te = self._feedDict(D['Xte'], D['Yte'], stepTr ,teIdx)
                    if 'class' in self.model:

                           if accNum == 500:
                                accNum = 0
                           claTe, _y = sess.run(self._resp, feed_dict = FD_te)
                           self.pred[stepTr] = [_y,[1,0]]
                           ansTe[accNum,:] = np.squeeze(claTe)

                           claTr, _ = sess.run(self._resp, feed_dict = FD_tr)
                           ansTr[accNum,:] = np.squeeze(claTr)

                           accNum += 1

                    self.lossTr[stepTr] = sess.run(self._ngml, feed_dict = FD_tr)
                    self.grad[stepTr]   = sess.run(self._grad, feed_dict = FD_tr)

                                    #Tracking variables in v2track
                    if self.sampRate > 0 and not stepTr%self.sampRate:
                        self._trackVar( nbSamp, samp, self.v2track )
                        samp +=1

                if detail and stepTr % self.dispStep == 0:

                    #trSpars = sess.run(self._sparsC, feed_dict = FD_tr)

                    #Testing fit with new data
                    lossTe = sess.run(self._ngml, feed_dict = FD_te) 
                    self.lossTe.append(lossTe) 

                    #Calculating accuraty for classification
                    if 'class' in self.model:
                       accTe = (np.sum(ansTe))/(500*self.batchSize)
                       self.acc.append(accTe)

                       accTr = (np.sum(ansTr))/(500*self.batchSize)

                       #Printing progress 
                       print( " Iter: " + str(stepTr) + "/" + str(self.nbIters)         +  
                               "   ~  Tr Loss: " + "{:.6f}".format(self.lossTr[stepTr]) +
                               "   ~  Tr Acc: "  + "{:.2f}".format(accTr*100)           + 
                               "   |  Te Loss: " + "{:.6f}".format(lossTe)              +
                               "   ~  Te Acc "   + "{:.2f}".format(accTe*100)     )

                    else:
                      print( " Iter: " + str(stepTr) + "/" + str(self.nbIters)           +  
                               "   ~  Tr Loss: " + "{:.6f}".format(self.lossTr[stepTr]) + 
                               "   |  Te Loss: " + "{:.6f}".format(lossTe)  )

   
                #Running backprop
                sess.run(self.optimizer, FD_tr)

                #Applying masks
                if self.masks:
                  sess.run(self.masking, FD_tr)

                stepTr  += 1
                stepBat += 1

            #Saving variables final state
            self.evalVars = {v.name: v.eval() for v in tf.trainable_variables()}
            
            if detail:
                #Final accuracy
                self._finalAcc(D,sess) #Final accuracy

                #Saving variables
                self.saver.save(sess, savepath)
                self.saver.save(sess, backupPath)

                if 'class' in self.model:
                  print('\nFinal training accuracy : {:.2f} '.format(self.AccTr))
                  print(  'Final testing accuracy  : {:.2f} '.format(self.AccTe))

                print('\nTotal time:  ' + str(datetime.timedelta(seconds = time.time()-t)))
            else:
                self.AccTr = -1
                self.AccTe = -1

            #Final accuracy
            self._finalAcc(D,sess) #Final accuracy

        return self.AccTe

    def _classiPred(self):
      # Classification models prediction

        out  = tf.nn.sigmoid(self._Z2)
        #Whether answer is right
        _Y = tf.round(out)
        Y  = self._Y # tf.constant([0,1], dtype = "int64")

        resp = tf.equal(Y,_Y) 
        return resp, _Y

    def _finalAcc(self,D,sess):
        ''' Will calculate the finnal accuracy on training and
            testing sets.''' 

        if 'class' in self.model:

          #Creating feeding dictionnaries 
          finalAccTr_D = self._feedDict(D['Xtr'],D['Ytr'])
          finalAccTe_D = self._feedDict(D['Xte'],D['Yte'])

          #Number of examples per label
          nlabTr1 = len(D['Ytr'][0]); nlabTe1 = len(D['Yte'][0])

          #Calculating the prediction acc
          AccTr,self.respTr = sess.run(self._resp, feed_dict = finalAccTr_D)
          AccTe,self.respTe = sess.run(self._resp, feed_dict = finalAccTe_D)

          #Taking the average prediction acc of all examples
          AccTr1 = np.mean(AccTr[:nlabTr1]); AccTr0 = np.mean(AccTr[nlabTr1:])
          AccTe1 = np.mean(AccTe[:nlabTe1]); AccTe0 = np.mean(AccTe[nlabTe1:])

          #Converting to pourcentage
          self.AccTr = (AccTr1+AccTr0)*50
          self.AccTe = (AccTe1+AccTe0)*50

        else:

          #Sampling proportion for training and testing sets
          sampPropTr = .10 
          sampProbTe = .50

          #Number of samples for each set
          sampTrSize = int( sampPropTr * len(D['Ytr']) ) 
          sampTeSize = int( sampProbTe * len(D['Yte']) )

          #Indexes of samples for each set
          idxTr = np.random.permutation(len(D['Ytr']))[:sampTrSize] 
          idxTe = np.random.permutation(len(D['Yte']))[:sampTeSize]

          #Creating feeding dictionnaries
          finalAccTr_D = self._feedDict( D['Xtr'][idxTr, ...], D['Ytr'][idxTr, :] )
          finalAccTe_D = self._feedDict( D['Xte'][idxTe, ...], D['Yte'][idxTe, :] )

          #Making the prediction for all sequences
          Ztr = sess.run(self._Z2, feed_dict = finalAccTr_D)
          Zte = sess.run(self._Z2, feed_dict = finalAccTe_D)

          #Calculating the correlation coefficient between pred and real
          self.AccTr = np.mean(np.diag(corr2_coeff(D['Ytr'],Ztr)))
          self.AccTe = np.mean(np.diag(corr2_coeff(D['Yte'],Zte)))


    def _feedDict(self, Dx, Dy, stepTr= None, idx = None):


      if 'class' in self.model:

        if not stepTr == None:
          idxS  = idx[0]
          idxNS = idx[1]

          FD ={ self._X : np.vstack([ Dx[0][idxS[:, stepTr],:],
                                      Dx[1][idxNS[:,stepTr],:] ]), 
                self._Y : np.vstack([ [1] * int(self.batchSize/2),
                                      [0] * int(self.batchSize/2) ]),
                self._batch     : stepTr,
                self._batchSize : self.batchSize,
                self._keepProb  : self.keepProb   }
        else:
          #For final testing
          FD ={ self._X : np.vstack([ Dx[0], Dx[1] ]),
                self._Y : np.hstack([ [[1] * len(Dx[0])],
                                      [[0] * len(Dx[1])] ]).T,
                self._batch     : 1,
                self._batchSize : len(Dx[0]) + len(Dx[1]),
                self._keepProb  : 1.0  }

      else:

        if not stepTr == None:
          FD = { self._X : Dx[ idx[:,stepTr], ... ],
                 self._Y : Dy[ idx[:,stepTr], :   ],
                 self._batch     : stepTr,
                 self._batchSize : self.batchSize  }

        else:
          #For final testing
          FD = { self._X         : Dx,
                 self._Y         : Dy,
                 self._batch     : 1,
                 self._batchSize : len(Dy) }

      return FD


    def _trackVar(self, nbSamp, samp, v2track):
        ''' 
        Will save the variables overtime at a given sampling rate.

        _______________________________________________________________

                                     ARGUMENTS
        _______________________________________________________________

        nbSamp  : total number of samples
        samp    : Current sample
        v2track : Contains the list of variables to track
        _______________________________________________________________

        '''

        #Values of variables of cu1rent sample
        vTrackVal = {v: self.vnames[v+':0'].eval() for v in v2track}

        #Initializing dictionnary
        if not hasattr(self, 'vTracked'):

            self.vTracked = {}
            for v in v2track:
                vdim = np.hstack([nbSamp,self.vnames[v+':0'].get_shape().as_list()])
                self.vTracked[v] = np.zeros(vdim)
        
        #Storing variables values at current sample
        for v in v2track:
            self.vTracked[v][samp,:] = vTrackVal[v]

        #Storing only direct connectivity
        if samp == nbSamp-1:
            tt = [('RNNCell' in var and 'Matrix' in var) for var in v2track]
            if any(tt):
                vidx = tt.index(True) #Variable index

                #If using __NGCmodel__ model
                if self.model == '__NGCmodel__':
                    dirC = self.vTracked[ v2track[vidx] ][: , self.nInput: -self.nhidGlob,
                                                            :-self.nhidGlob ]
                    self.vTracked['direct_W'] = dirC

        
    def showVars(self):
        #Will plot all variables

        idx   = 0 # Variable index
        spIdx = 0 # Subplot index

        for v in self.vnames:
            
            if spIdx % 4 == 0:
                plt.figure(figsize = (20,5))
                spIdx = 1
            
            #Dimension of variable
            dim = np.shape(self.evalVars[v])

            if len(dim)>1 and dim[0]>1 and dim[1]>1:

                #Plotting 2 dimensional variables
                plt.subplot(1,3,spIdx)
                
                #Plotting network H->H connectivity matrix only
                if 'BasicRNNCell' in v and 'Matrix' in v:
                      plt.imshow(self.evalVars[v][self.nhidNetw:,:], aspect = 'auto', interpolation = 'None')
                else:
                      plt.imshow(self.evalVars[v], aspect = 'auto', interpolation = 'None') 
                        
                plt.title(v[:-2], fontsize = 15)
                plt.colorbar()

            else:

                #Plotting one dimensional variables
                plt.subplot(1,3,spIdx)
                plt.plot(self.evalVars[v], 'x')
                plt.title(v[:-2], fontsize = 15)
                
            spIdx +=1
            idx   +=1


    def vidTrack(self, v2track = None, norm = True):
        ''' 
            Will diplay images of tracked variables in v2track
            over sample, giving a video. 


        _______________________________________________________________

                                    ARGUMENTS
        _______________________________________________________________

        nbSamp  : total number of samples
        samp    : Current sample
        v2track : Contains the list of variables to track
        _______________________________________________________________


        '''

        if not v2track:
            v2track = self.v2track

        #Function variables 
        nSample = self.vTracked[v2track[0]].shape[0] #Number of sample
        nVars   = len(v2track)                  #Number of variables to display
        nRow    = int(np.ceil(nVars/3))         #Number of subplot row

        # Number of collumns
        if   nVars  >= 3: nCol = 3 
        elif nVars  <  3: nCol = nVars 

    
        #Using only v2track variables
        vTracked = {v: self.vTracked[v].copy()  for v in v2track}  #Values
        dims     = {v: vTracked[v][0,...].shape for v in vTracked} #Dimensions

        #Normalizing each sample to see how things evolve
        if norm:
            for v in vTracked:
                for s in range(nSample):
                    vTracked[v][s,...] = vTracked[v][s,...]/abs(vTracked[v][s,...]).max()
                
        #Display 
        fig = plt.figure(figsize = (30,15))
        plt.hold(False)
        for s in range(nSample):

            spIdx = 1 # Subplot index
            for v in vTracked:
                ax = plt.subplot(nRow,nCol,spIdx)

                if len(dims[v])>1 and dims[v][0]>1 and dims[v][1]>1:
                    #Plotting 2 dimensional variables
                    plt.imshow(vTracked[v][s,...],
                               aspect = 'auto', clim=(-1,1),
                               interpolation = 'None') 
                    
                else:
                    #Plotting one dimensional variables
                    plt.plot(vTracked[v][s,:], 'x', ms = 20, mew = 3)
                    ax.set_ylim(-1,1)
                
                plt.title(v, fontsize = 15)
                spIdx += 1

                plt.draw()

            display.clear_output(wait=True)
            display.display(plt.gcf())

        
        display.clear_output()


def plotfit(paramFile, argDict= None, idx = range(1000), ckpt='/tmp/backup.ckpt'):
    ''' 
    Will plot the real values and the fit of the model on top of it
    in order to evaluate the fit of the model.

    _________________________________________________________________________

                                   ARGUMENTS
    _________________________________________________________________________
        
         argDict   : Overwriting certain paramers. Has to be of type dict
         paramFile : Parameter file to run (in optoConnMain)
         idx       : indexes of examples to plot
         ckpt      : ckpt can either be a full ckpt path, or only ckpt name.
                       ~> If only the name is provided, plotfit will look into 
                             optoConn/checkpoints/
                       ~> If agument not provided, plotfit will use the backup 
                             ckpt in /tmp.

    _________________________________________________________________________

    '''

    #Recovering main file function
    mainFile = getattr(ACM, paramFile)
    nbPoints = len(idx)

    argDict['batchSize'] = nbPoints #Adjusting batchsize for nb of points

    #Building graph
    graphFit, dataDict, L = mainFile(argDict, run = False)

    X = dataDict['FitX'][idx, ...] # Input
    Y = dataDict['FitY'][idx, :]   # Label

    N = Y.shape[1]

    #Loading ckpt if checkpoint name only is provided
    if ckpt[0] != '/':
        ckpt = graphFit._mPath + 'checkpoints/' + ckpt

    #Passing data in model
    with tf.Session(graph=graphFit.graph) as sess:
        graphFit.saver.restore(sess, ckpt)
        with tf.variable_scope("") as scope:
            scope.reuse_variables()

            #X is transposed since it does not go through batch creation function
            _Z2 = sess.run(graphFit._Z2, feed_dict = { graphFit._X : X })

    #Plotting test set
    plt.figure(figsize=(20, 5))
    plt.imshow(Y.T, aspect='auto') ; 
    plt.title('Sample of Simulated Calcium Data', fontsize = 14)
    plt.xlabel('Frames (time)', fontsize = 14) ; plt.ylabel('Neurons', fontsize = 14) ; plt.colorbar()

    #Plotting prediction on test set
    plt.figure(figsize=(20, 5))
    plt.imshow(_Z2.T, aspect='auto') ; plt.title('Model Predictions', fontsize = 14)
    plt.ylabel('Neurons', fontsize = 14) ; plt.xlabel('Time (frames)', fontsize = 14) ; plt.colorbar()

    #Printing the difference between data and prediction
    plt.figure(figsize=(20, 5))
    plt.imshow((Y-_Z2).T, aspect='auto') ; plt.title('Real - Model', fontsize = 14)
    plt.ylabel('Neurons', fontsize = 14) ; plt.xlabel('Time (frames)') ; plt.colorbar()

    n = np.random.randint(N)

    plt.figure(figsize=(20, 5))
    plt.plot(  Y[:,n], 'b', label = 'real')
    plt.plot(_Z2[:,n], 'r', label = 'pred')
    plt.xlabel('Time (frames)') ; plt.ylabel('Neurons')
    plt.title('Neuron {} activity and prediction'.format(n))
    plt.legend()

    plt.show()

    return Y, _Z2


#    def sensitivityA(self, data, ckpt='/tmp/backup.ckpt'):



