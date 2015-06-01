from threeML.minimizer import minimization
from threeML.exceptions import CustomExceptions

import collections

import numpy
import scipy.optimize
import scipy.stats
import sys
import matplotlib.pyplot as plt

from astropy.table import Table

from IPython.display import display

import numpy as np

def cartesian(arrays, out=None):
    """
    Generate a cartesian product of input arrays.

    Parameters
    ----------
    arrays : list of array-like
        1-D arrays to form the cartesian product of.
    out : ndarray
        Array to place the cartesian product in.

    Returns
    -------
    out : ndarray
        2-D array of shape (M, len(arrays)) containing cartesian products
        formed of input arrays.

    Examples
    --------
    >>> cartesian(([1, 2, 3], [4, 5], [6, 7]))
    array([[1, 4, 6],
           [1, 4, 7],
           [1, 5, 6],
           [1, 5, 7],
           [2, 4, 6],
           [2, 4, 7],
           [2, 5, 6],
           [2, 5, 7],
           [3, 4, 6],
           [3, 4, 7],
           [3, 5, 6],
           [3, 5, 7]])

    """

    arrays = [np.asarray(x) for x in arrays]
    dtype = arrays[0].dtype

    n = np.prod([x.size for x in arrays])
    if out is None:
        out = np.zeros([n, len(arrays)], dtype=dtype)

    m = n / arrays[0].size
    out[:,0] = np.repeat(arrays[0], m)
    if arrays[1:]:
        cartesian(arrays[1:], out=out[0:m,1:])
        for j in xrange(1, arrays[0].size):
            out[j*m:(j+1)*m,1:] = out[0:m,1:]
    return out

class JointLikelihood(object):
  
  def __init__(self, likelihoodModel, dataList, **kwargs):
    
    #Process optional keyword parameters
    self.verbose             = False
        
    for k,v in kwargs.iteritems():
      
      if(k.lower()=="verbose"):
      
        self.verbose           = bool(kwargs["verbose"])
    
        
    self.likelihoodModel      = likelihoodModel
        
    self.dataList             = dataList
    
    for dataset in self.dataList.values():
      
      dataset.setModel(self.likelihoodModel)
    
    #This is to keep track of the number of calls to the likelihood
    #function
    self.ncalls              = 0
    
    self.setMinimizer('iMinuit')
    
  pass
  
  def preFit(self):
    
    #This is a simple scan through the normalization parameters to guess
    #a good starting point for them (if we start too far from the data,
    #minuit and the other minimizers will have trouble)
    
    #Get the list of free parameters
    freeParams               = self.likelihoodModel.getFreeParameters()
    
    #Now isolate the normalizations, and use them as free parameters in the loglikelihood
    
    self.freeParameters      = collections.OrderedDict()
    
    for (k,v) in freeParams.iteritems():
      
      if v.isNormalization():
        
        self.freeParameters[k] = v
        
    #Prepare the grid of values to scan
    
    grids                    = []
    
    for norm in self.freeParameters.values():
            
      grids.append(numpy.logspace( numpy.log10( norm.minValue ),
                                   numpy.log10( norm.maxValue ), 
                                   50 ))
      
    #Compute the global likelihood at each point in the grid
    globalGrid               = cartesian(grids)
    
    logLikes                 = map(self.minusLogLikeProfile, globalGrid)
    
    idx                      = numpy.argmin(logLikes)
    #print("Minimum is %s with %s" %(logLikes[idx],globalGrid[idx]))
    
    for i,norm in enumerate(self.freeParameters.values()):
      
      norm.setValue(globalGrid[idx][i])
      norm.setDelta(norm.value / 40)
    
  def minusLogLikeProfile(self, *trialValues):
      
      #Keep track of the number of calls
      self.ncalls                += 1
      
      #Assign the new values to the parameters
      
      for i,parname in enumerate(self.freeParameters.keys()):
        
        self.likelihoodModel.parameters[parname[0]][parname[1]].setValue(trialValues[i])
      
            
      #Now profile out nuisance parameters and compute the new value 
      #for the likelihood
      
      globalLogLike              = 0
      
      for dataset in self.dataList.values():
          
          try:
          
            globalLogLike         += dataset.innerFit()
          
          except CustomExceptions.ModelAssertionViolation:
            
            #This is a zone of the parameter space which is not allowed. Return
            #a big number for the likelihood so that the fit engine will avoid it
            return 1e6
          
          except:
            
            #Do not intercept other errors
            raise
          
          #dataset.getLogLike()      
      
      if("%s" % globalLogLike=='nan'):
        print("Warning: these parameters returned a logLike = Nan: %s" %(trialValues,))
        return 1e6
      
      if(self.verbose):
        print("Trying with parameters %s, resulting in logL = %s" %(trialValues,globalLogLike))
      
      return globalLogLike*(-1)
  
  
  def setMinimizer(self,minimizer):
  
    if(minimizer.upper()=="IMINUIT"):
    
      self.Minimizer          = minimization.iMinuitMinimizer
    
    elif(minimizer.upper()=="MINUIT"):
    
      self.Minimizer          = minimization.MinuitMinimizer
    
    elif(minimizer.upper()=="SCIPY"):
    
      self.Minimizer          = minimization.ScipyMinimizer
    
    elif(minimizer.upper()=="BOBYQA"):
    
      self.Minimizer          = minimization.BOBYQAMinimizer
    
    else:
    
      raise ValueError("Do not know minimizer %s" %(minimizer))
  
  def fit(self):
    
    #Pre-fit: will fix the normalizations so that they are not too far
    #from the data (which would make the fitting below fail)
    self.preFit()
    
    #Isolate the free parameters
    #NB: nuisance parameters are NOT in this dictionary
    
    self.freeParameters       = self.likelihoodModel.getFreeParameters()
    
    #Now check and fix if needed all the deltas of the parameters
    #to 5% of their value (otherwise the fit will be super-slow)
    for k,v in self.freeParameters.iteritems():
      
      if (abs(v.delta) < abs(v.value) * 0.1):
                
        v.setDelta(abs(v.value) * 0.1)
    
    #Instance the minimizer
    self.minimizer            = self.Minimizer(self.minusLogLikeProfile,
                                               self.freeParameters)
    
    #Perform the fit
    xs, logLmin          = self.minimizer.minimize()
    
    #Print results
    print("Best fit values:\n")
    self.minimizer.printFitResults()
    
    print("\nCorrelation matrix:\n")
    self.minimizer.printCorrelationMatrix()
    
    print("\nMinimum of -logLikelihood is: %s\n" %(logLmin))
    
    print("Contributions to the -logLikelihood at the minimum:\n")
    
    data                      = []
    nameLength                = 0
    
    for dataset in self.dataList.values():
      
      nameLength              = max(nameLength, len(dataset.getName()) + 1)
      data.append([dataset.getName(),dataset.getLogLike()*(-1)])
    
    table                     = Table( rows  = data,
                                       names = ["Detector","-LogL"],
                                       dtype = ('S%i' %nameLength, float))
    
    display(table)
        
    return xs,logLmin    
  
  def getErrors(self,fast=False):
    
    if(not hasattr(self,'minimizer')):
      raise RuntimeError("You have to run the .fit method before calling errors.")
    
    return self.minimizer.getErrors(fast)
  
  def getLikelihoodProfiles(self):
    
    if(not hasattr(self,'minimizer')):
      raise RuntimeError("You have to run the .fit method before calling errors.")
    
    return self.minimizer.getLikelihoodProfiles()
  
  def getContours(self,param1,param2):
    
    return self.minimizer.getContours(param1,param2)
  
#  def _restoreBestFitValues(self):
#    #Restore best fit values
#    for k in self.freeParameters.keys():
#      self.freeParameters[k].setValue(self.bestFitValues[k])
#      self.modelManager[k].setValue(self.bestFitValues[k])
#    pass  
#  pass
  
#  def getErrors(self,confidenceLevel=0.68268949213708585,**kwargs):
#    '''
#    Compute asymptotic errors using the Likelihood Ratio Test. Usage:
#    
#    computeErrors(0.68)
#    
#    will compute the 1-sigma error region, while:
#    
#    computeErrors(0.99)
#    
#    will compute the 99% c.l. error region, and so on. Alternatively, you
#    can specify the number of sigmas corresponding to the desired c.l., as:
#    
#    computeErrors(sigma=1)
#    
#    to get the 68% c.l., or:
#    
#    computeErrors(sigma=2)
#    
#    to get the ~95% c.l.
#    '''
#    
#    equivalentSigma           = None
#    plotProfiles              = False
#    for k,v in kwargs.iteritems():
#      if(k.lower()=="sigma"):
#        equivalentSigma       = float(v)
#      elif(k.lower()=="profiles"):
#        plotProfiles          = bool(v)
#    pass
#    
#    if(confidenceLevel > 1.0 or confidenceLevel <= 0.0):
#      raise RuntimeError("Confidence level must be 0 < cl < 1. Ex. use 0.683 for 1-sigma interval")
#    
#    #Get chisq critical value corresponding to this confidence level
#    if(equivalentSigma==None):
#      equivalentSigma         = scipy.stats.norm.isf((1-confidenceLevel)/2.0) 
#    else:
#      confidenceLevel         = 1-(scipy.stats.norm.sf(equivalentSigma)*2.0)
#    pass
#    
#    criticalValue             = scipy.stats.chi2.isf([1-confidenceLevel],1)[0]
#    
#    print("Computing %.3f c.l. errors (chisq critical value: %.3f, equivalent sigmas: %.3f sigma)" %(confidenceLevel,criticalValue,equivalentSigma))
#    
#    #Now computing the errors
#    if(len(self.bestFitValues.keys())==0):
#      raise RuntimeError("You have to perform a fit before calling computeErrors!")
#    
#    #Find confidence intervals for all parameters, except nuisance ones
#    paramNames                = self.bestFitValues.keys()
#    paramList                 = []
#    for par in paramNames:
#      if(self.modelManager[par].isNuisance()):
#        continue
#      else:
#        paramList.append(par)
#      pass
#    pass
#    
#    confInterval              = collections.OrderedDict()
#    
#    for i,parname in enumerate(paramList):
#      
#      sys.stdout.write("Computing error for parameter %s...\n" %(parname))
#      
#      #Get the list of free parameters
#      self.freeParameters     = self.modelManager.getFreeParameters()
#      
#      self._restoreBestFitValues()
#      
#      #Remove the current parameter from the list of free parameters,
#      #so that it won't be varied
#      self.freeParameters.pop(parname)
#      
#      #Build the profile logLike for this parameter
#      
#      def thisProfileLikeRenorm(newValue):
#        
#        self._restoreBestFitValues()
#        
#        #Set the current parameter to its current value
#        
#        #newValue              = newValue[0]
#        self.modelManager[parname].setValue(newValue)
#        
#        #Fit all other parameters
#        
#        minimizer             = self.Minimizer(self.minusLogLikeProfile,self.freeParameters)
#        _,_,proflogL          = minimizer.minimize(False,False)
#        
#        #Subtract the minimum and the critical value/2, so that when this is 0 the true profileLogLike is 
#        #logL+critical value/2.0
#        #(the factor /2.0 comes from the LRT, which has 2*deltaLoglike as statistic)
#        
#        return proflogL-self.logLmin-criticalValue/2.0
#      pass
#      
#      #Find the values of the parameter for which the profile logLike is
#      # equal to the minimum - critical value/2.0, i.e., when thisProfileLikeRenorm is 0
#      
#      #We will use the approximate error (the sqrt of the diagonal of the covariance matrix)
#      #as starting point for the search. Since it represents the approximate 1 sigma error,
#      #we have to multiply it by the appropriate number of sigmas
#      
#      bounds                  = []
#      for kind in ['lower','upper']:
#        if(kind=='lower'):
#          for i in [1.0,1.1,1.5,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0]:
#            approxSolution        = self.bestFitValues[parname]-i*equivalentSigma*abs(self.approxErrors[parname])
#            if(thisProfileLikeRenorm(approxSolution) > 0):
#              break
#        else:
#          for i in [1.0,1.1,1.5,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0]:
#            approxSolution        = self.bestFitValues[parname]+i*equivalentSigma*abs(self.approxErrors[parname])
#            if(thisProfileLikeRenorm(approxSolution) > 0):
#              break
#        pass
#        
#        if(approxSolution < self.modelManager[parname].minValue):
#          approxSolution          = self.modelManager[parname].minValue*1.1
#        pass
#        
#        if(approxSolution > self.modelManager[parname].maxValue):
#          approxSolution          = self.modelManager[parname].maxValue*0.9
#        pass
#        
#        tolerance                 = abs(self.bestFitValues[parname])/10000.0
#        
#        if(self.verbose):
#          print("Approx solution for %s bound is %s, tolerance is %s" %(kind,approxSolution,tolerance))
#        try:
#          #This find the root of thisProfileLikeRenorm, i.e., the value of its argument for which
#          #it is zero
#          #results                 = scipy.optimize.root(thisProfileLikeRenorm,
#          #                                              approxSolution,
#          #                                              method='lm')
#          results                 = scipy.optimize.brentq(thisProfileLikeRenorm,approxSolution,self.bestFitValues[parname],rtol=1e-3)
#          
#        except:
#          print("Error search for %s bound for parameter %s failed. Parameter is probably unconstrained." %(kind,parname))
#          raise
#        else:
#          
#          #if(results['success']==False):
#          #  print RuntimeError("Could not find a solution for the %s bound confidence for parameter %s" %(kind,parname))
#          #  raise
#          #bounds.append(results['x'][0])
#          bounds.append(results) 
#      pass
#                  
#      confInterval[parname] = [min(bounds),max(bounds)]
#    pass
#    
#    self.freeParameters     = self.modelManager.getFreeParameters()
#    
#    print("\nBest fit values and their errors are:")
#    for parname in confInterval.keys():
#      value                   = self.bestFitValues[parname]
#      error1,error2           = confInterval[parname]
#      print("%-20s = %6.3g [%6.4g,%6.4g]" %(parname,value,error1-value,error2-value))
#    pass
#    
#    if(plotProfiles):
#      #Plot the profile likelihoods for each parameter
#      npar                    = len(confInterval.keys())
#      nrows                   = npar/2
#      ncols                   = 2
#      if(nrows*ncols < npar):
#        nrow                 += 1
#      pass
#      
#      fig,subs                = plt.subplots(nrows,ncols)
#      
#      for i,sub,(parname,interval) in zip(range(npar),subs.flatten(),confInterval.iteritems()):
#        #Remove this parameter from the freeParameters list
#        #Get the list of free parameters
#        self.freeParameters     = self.modelManager.getFreeParameters()
#      
#        self._restoreBestFitValues()
#        
#        #Remove the current parameter from the list of free parameters,
#        #so that it won't be varied
#        self.freeParameters.pop(parname)
#        
#        val                   = self.bestFitValues[parname]
#        errorM                = interval[0]-val
#        errorP                = interval[1]-val   
#        grid                  = numpy.linspace(val+1.1*errorM,val+1.1*errorP,10)
#        grid                  = numpy.append(grid,val)
#        grid.sort()
#        logLonGrid            = []
#        for g in grid:
#          self._restoreBestFitValues()
#          logLonGrid.append(2*(thisProfileLikeRenorm(g)+criticalValue/2.0))
#        pass
#        sub.plot(grid,logLonGrid)
#        sub.set_xlabel("%s" %(parname))
#        sub.set_ylabel(r"2 ($L_{prof}$-L$_{0}$)")
#        sub.axhline(criticalValue,linestyle='--')
#        #Reduce the number of x ticks
#        sub.locator_params(nbins=5,axis='x')
#      pass
#      
#      plt.tight_layout()
#      
#    pass
#    
#    return confInterval
#  pass
