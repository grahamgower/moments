import numpy as np
import math
import os,sys

from moments.LD import Numerics
from moments.LD import Util

import copy
import moments
from moments.Misc import perturb_params
from moments.Misc import delayed_flush
from moments.LD.LDstats_mod import LDstats

from scipy.special import gammaln
import scipy.optimize

"""
Adapted from moments/dadi to infer input parameters of demographic model
Usage is the same as moments.Inference, but inference using LD statistics 
requires a bit more for inputs
There are two options: run inference with LD stats alone, or LD+AFS
If we are using LD stats alone, data = [means, varcovs], a list of statistics 
means and the bootstrapped variance-covariance matrix
If we use LD+AFS, data = [means, varcovs, fs]
To use the frequency spectrum in the inference, we set the flag use_afs=True

"""

_counter = 0

def sigmaD2(y, normalization=1):
    """
    y : LDstats object for n populations
    normalization : normalizing population (normalized by pi2_i_i_i_i and H_i_i), default set to 1
    """
    if normalization > y.num_pops:
        raise ValueError("normalization index cannot be greater than number of populations.")
    
    for i in range(len(y))[:-1]:
        y[i] /= y[i][y.names()[0].index('pi2_{0}_{0}_{0}_{0}'.format(normalization))]
    y[-1] /= y[-1][y.names()[1].index('H_{0}_{0}'.format(normalization))]
    
    return y

def bin_stats(model_func, params, rho=[], theta=0.001, kwargs={}):
    if len(rho) < 2:
        raise ValueError("number of recombination rates must be greater than one")
    ## XX check if sorted...
    
    ## how to pass arbitrary arguments... thinking about pop_ids (right now, set pop_ids in model_func)
    rho_mids = (np.array(rho[:-1]) + np.array(rho[1:])) / 2
    y_edges = model_func(params, rho=rho, theta=theta, **kwargs)
    y_mids = model_func(params, rho=rho_mids, theta=theta, **kwargs)
    y = [1./6 * (y_edges[i] + y_edges[i+1] + 4*y_mids[i]) for i in range(len(rho_mids))]
    y.append(y_edges[-1])
    return LDstats(y, num_pops=y_edges.num_pops, pop_ids=y_edges.pop_ids)

def remove_normalized_lds(y, normalization=1):
    to_delete_ld = y.names()[0].index('pi2_1_1_1_1')
    to_delete_h = y.names()[1].index('H_1_1')
    for i in range(len(y)-1):
        y[i] = np.delete(y[i], to_delete_ld)
    y[-1] = np.delete(y[-1], to_delete_h)
    return y

def remove_normalized_data(means, varcovs, normalization=1, num_pops=1):
    stats = Util.moment_names(num_pops)
    to_delete_ld = stats[0].index('pi2_{0}_{0}_{0}_{0}'.format(normalization))
    to_delete_h = stats[1].index('H_{0}_{0}'.format(normalization))
    ms = []
    vcs = []
    for i in range(len(means)-1):
        ms.append(np.delete(means[i], to_delete_ld))
        vcs.append(np.delete(np.delete(varcovs[i], to_delete_ld, axis=0), to_delete_ld, axis=1))
    ms.append(np.delete(means[-1], to_delete_h))
    vcs.append(np.delete(np.delete(varcovs[-1], to_delete_h, axis=0), to_delete_h, axis=1))
    return ms, vcs

def remove_nonpresent_statistics(y, statistics=[[],[]]):
    """
    statistics is a list of lists for two and one locus statistics to keep
    """
    to_delete = [[],[]]
    for j in range(2):
        for i,s in enumerate(y.names()[j]):
            if s not in statistics[j]:
                to_delete[j].append(i)
    for i in range(len(y)-1):
        y[i] = np.delete(y[i], to_delete[0])
    y[-1] = np.delete(y[-1], to_delete[1])
    return y

def multivariate_normal_pdf(x,mu,Sigma):
    p = len(x)
    return np.sqrt(np.linalg.det(Sigma)/(2*math.pi)**p) * np.exp( -1./2 * 
                        np.dot( np.dot( (x-mu).transpose() , 
                                np.linalg.inv(Sigma) ) , x-mu ) )

def ll(x,mu,Sigma):
    """
    x = data
    mu = model function output
    Sigma = variance-covariance matrix
    """
    if len(x) == 0:
        return 0
    else:
        return -1./2 * np.dot( np.dot( (x-mu).transpose() , 
                               np.linalg.inv(Sigma) ) , x-mu ) 
                               #- len(x)*np.pi - 1./2*np.log(np.linalg.det(Sigma)) 

def ll_over_bins(xs,mus,Sigmas):
    """
    xs = list of data arrays
    mus = list of model function output arrays
    Sigmas = list of var-cov matrices
    Lists must be in the same order
    Each bin is assumed to be independent, so we call ll(x,mu,Sigma) 
      for each bin
    """
    it = iter([xs,mus,Sigmas])
    the_len = len(next(it))
    if not all(len(l) == the_len for l in it):
        raise ValueError('Lists of data, means, and varcov matrices must be the same length')
    ll_vals = []
    for ii in range(len(xs)):
        ll_vals.append(ll(xs[ii],mus[ii],Sigmas[ii]))
    ll_val = np.sum(ll_vals)
    return ll_val

_out_of_bounds_val = -1e12
def _object_func(params, model_func, means, varcovs, fs=None,
                 rs = None, theta=None, u=None, Ne=None,
                 lower_bound=None, upper_bound=None,
                 verbose=0, flush_delay=0,
                 normalization=1,
                 func_args=[], func_kwargs={}, fixed_params=None,
                 use_afs=False, Leff=None, multinom=True, ns=None,
                 statistics=None, pass_Ne=False,
                 output_stream=sys.stdout):
    global _counter
    _counter += 1
    
    # Deal with fixed parameters
    params_up = _project_params_up(params, fixed_params)
    
    # Check our parameter bounds
    if lower_bound is not None:
        for pval,bound in zip(params_up, lower_bound):
            if bound is not None and pval < bound:
                return -_out_of_bounds_val
    if upper_bound is not None:
        for pval,bound in zip(params_up, upper_bound):
            if bound is not None and pval > bound:
                return -_out_of_bounds_val
    
    all_args = [params_up] + list(func_args)
    
    if theta is None:
        if Ne is None:
            Ne = params_up[-1]
            theta = 4*Ne*u
            rhos = [4*Ne*r for r in rs]
            if pass_Ne == False:
                all_args = [all_args[0][:-1]]
            else:
                all_args = [all_args[0][:]]
        else:
            theta = 4*Ne*u
            rhos = [4*Ne*r for r in rs]
    else:
        if Ne is not None:
            rhos = [4*Ne*r for r in rs]
        
    ## first get ll of afs
    if use_afs == True:
        if Leff is None:
            model = theta * model_func[1](all_args[0],ns)
        else:
            model = Leff * theta * model_func[1](all_args[0],ns)
        if fs.folded:
            model = model.fold()
        if multinom == True:
            ll_afs = moments.Inference.ll_multinom(model,fs)
        else:
            ll_afs = moments.Inference.ll(model,fs)
    
    ## next get ll for LD stats
    func_kwargs = {'theta':theta, 'rho':rhos}
    stats = bin_stats(model_func[0], *all_args, **func_kwargs)
    stats = sigmaD2(stats, normalization=normalization)
    if statistics == None:
        stats = remove_normalized_lds(stats, normalization=normalization)
    else:
        stats = remove_nonpresent_statistics(stats, statistics=statistics)
    simp_stats = stats[:-1]
    het_stats = stats[-1]
        
    if use_afs == False:
        simp_stats.append(het_stats)
    
    ## resulting ll from afs (if used) plus ll from rho bins
    if use_afs == True:
        result = ll_afs + ll_over_bins(means, simp_stats, varcovs)
    else:
        result = ll_over_bins(means, simp_stats, varcovs)
    
    # Bad result
    if np.isnan(result):
        print("got bad results...")
        result = _out_of_bounds_val
        
    if (verbose > 0) and (_counter % verbose == 0):
        param_str = 'array([%s])' % (', '.join(['%- 12g'%v for v in params_up]))
        output_stream.write('%-8i, %-12g, %s%s' % (_counter, result, param_str,
                                                   os.linesep))
        delayed_flush(delay=flush_delay)
    
    return -result

def _object_func_log(log_params, *args, **kwargs):
    return _object_func(np.exp(log_params), *args, **kwargs)

def optimize_log_fmin(p0, data, model_func,
                 rs=None, theta=None, u=2e-8, Ne=None, 
                 lower_bound=None, upper_bound=None, 
                 verbose=0, flush_delay=0.5,
                 normalization=1,
                 func_args=[], func_kwargs={}, fixed_params=None, 
                 use_afs=False, Leff=None, multinom=False, ns=None,
                 statistics=None, pass_Ne=False):
    """
    p0 : initial guess (demography parameters + theta)
    data : [means, varcovs, fs (optional, use if use_afs=True)]
    means : list of mean statistics matching bins (has length len(rs)-1)
    varcovs : list of varcov matrices matching means
    model_func : demographic model to compute statistics for a given rho
                 If we are using AFS, it's a list of the two models [LD, AFS]
                 If it's LD stats alone, it's just a single LD model (still passed as a list)
    rs : list of raw recombination rates, to be scaled by Ne (either passed or last value in list of params)
    theta : this is population scaled per base mutation rate (4*Ne*mu, not 4*Ne*mu*L)
    u : raw per base mutation rate, theta found by 4*Ne*u
    Ne : pass if we want a fixed effective population size to scale u and r
    lower_bound : 
    upper_bound : 
    verbose : 
    flush_delay : 
    func_args : 
    func_kwargs : 
    fixed_params : 
    use_afs : we pass a model to compute the frequency spectrum and use that instead of heterozygosity statistics
    Leff : effective length of genome from which the fs was generated (only used if fitting to afs)
    multinom : only relevant if we are using the AFS, likelihood computed for scaled FS 
               vs fixed scale of FS from theta and Leff
    ns : sample size (only needed if we are using the frequency spectrum, as we ns does not affect mean LD stats) 
    statistics : If None, we only remove the normalizing statistic. Otherwise, we only
                 compute likelihoods over statistics passed here as [ld_stats (list), het_stats (list)]
    pass_Ne : if the function doesn't take Ne as the last parameter (which is used with the recombination
              map), wet to False. If the function also needs Ne, set to True.
    
    We can either pass a fixed mutation rate theta = 4*N*u, or we pass u and Ne (and compute theta),
        or we pass u and Ne is a parameter of our model to fit (which scales both the mutation rate and
        the recombination rates).
    We can either pass fixed rho values for the bins, or we pass r and Ne, or we pass r and Ne is a 
        parameter of our model, just as for the mutation rate.
    """
    output_stream = sys.stdout
    
    means = data[0]
    varcovs = data[1]
    if use_afs == True:
        try:
            fs = data[2]
        except IndexError:
            raise ValueError("if use_afs=True, need to pass frequency spectrum in data=[means,varcovs,fs]")
        
        if ns == None:
            raise ValueError("need to set ns if we are fitting frequency spectrum")
        
    else:
        fs = None
        
    if use_afs == True:
        raise ValueError("which mutation/theta parameters do we need to check and pass")
    
    if rs is None:
        raise ValueError("need to pass rs as bin edges")
    
    #if Ne is None:
    #    print("Warning: using last parameter in list of params as Ne")
    
    # get num_pops
    if Ne == None:
        if pass_Ne == False:
            y = model_func[0](p0[:-1])
        else:
            y = model_func[0](p0[:])
    else:
        y = model_func[0](p0)
    num_pops = y.num_pops
    
    # remove normalized statistics (or how should we handle the masking?)
    ms = copy.copy(means)
    vcs = copy.copy(varcovs)
    if statistics == None: # if statistics is not None, assume we already filtered out the data
        ms,vcs = remove_normalized_data(ms, vcs, normalization=normalization, num_pops=num_pops)
    
    args = (model_func, ms, vcs, fs, 
            rs, theta, u, Ne, 
            lower_bound, upper_bound, 
            verbose, flush_delay,
            normalization,
            func_args, func_kwargs, fixed_params, 
            use_afs, Leff, multinom, ns, 
            statistics, pass_Ne,
            output_stream)
    
    p0 = _project_params_down(p0, fixed_params)
    outputs = scipy.optimize.fmin(_object_func_log, np.log(p0), args=args, full_output=True, disp=False)
    
    xopt, fopt, iter, funcalls, warnflag = outputs
    xopt = _project_params_up(np.exp(xopt), fixed_params)
    
    return xopt, fopt

def optimize_log_powell(p0, data, model_func,
                 rs=None, theta=None, u=2e-8, Ne=None, 
                 lower_bound=None, upper_bound=None, 
                 verbose=0, flush_delay=0.5,
                 normalization=1,
                 func_args=[], func_kwargs={}, fixed_params=None, 
                 use_afs=False, Leff=None, multinom=False, ns=None,
                 statistics=None, pass_Ne=False):
    """
    p0 : initial guess (demography parameters + theta)
    data : [means, varcovs, fs (optional, use if use_afs=True)]
    means : list of mean statistics matching bins (has length len(rs)-1)
    varcovs : list of varcov matrices matching means
    model_func : demographic model to compute statistics for a given rho
                 If we are using AFS, it's a list of the two models [LD, AFS]
                 If it's LD stats alone, it's just a single LD model (still passed as a list)
    rs : list of raw recombination rates, to be scaled by Ne (either passed or last value in list of params)
    theta : this is population scaled per base mutation rate (4*Ne*mu, not 4*Ne*mu*L)
    u : raw per base mutation rate, theta found by 4*Ne*u
    Ne : pass if we want a fixed effective population size to scale u and r
    lower_bound : 
    upper_bound : 
    verbose : 
    flush_delay : 
    func_args : 
    func_kwargs : 
    fixed_params : 
    use_afs : we pass a model to compute the frequency spectrum and use that instead of heterozygosity statistics
    Leff : effective length of genome from which the fs was generated (only used if fitting to afs)
    multinom : only relevant if we are using the AFS, likelihood computed for scaled FS 
               vs fixed scale of FS from theta and Leff
    ns : sample size (only needed if we are using the frequency spectrum, as we ns does not affect mean LD stats) 
    
    We can either pass a fixed mutation rate theta = 4*N*u, or we pass u and Ne (and compute theta),
        or we pass u and Ne is a parameter of our model to fit (which scales both the mutation rate and
        the recombination rates).
    We can either pass fixed rho values for the bins, or we pass r and Ne, or we pass r and Ne is a 
        parameter of our model, just as for the mutation rate.
    """
    output_stream = sys.stdout
    
    means = data[0]
    varcovs = data[1]
    if use_afs == True:
        try:
            fs = data[2]
        except IndexError:
            raise ValueError("if use_afs=True, need to pass frequency spectrum in data=[means,varcovs,fs]")
        
        if ns == None:
            raise ValueError("need to set ns if we are fitting frequency spectrum")
        
    else:
        fs = None
        
    if use_afs == True:
        raise ValueError("which mutation/theta parameters do we need to check and pass")
    
    if rs is None:
        raise ValueError("need to pass rs as bin edges")
    
    #if Ne is None:
    #    print("Warning: using last parameter in list of params as Ne")
    
    # remove normalized statistics (or how should we handle the masking?)
    ms = copy.copy(means)
    vcs = copy.copy(varcovs)
    if statistics == None: # if statistics is not None, assume we already filtered out the data
        ms,vcs = remove_normalized_data(ms, vcs, normalization=normalization, num_pops=num_pops)
    
    # get num_pops
    if Ne == None:
        if pass_Ne == False:
            y = model_func[0](p0[:-1])
        else:
            y = model_func[0](p0[:])
    else:
        y = model_func[0](p0)
    num_pops = y.num_pops
    
    args = (model_func, ms, vcs, fs, 
            rs, theta, u, Ne, 
            lower_bound, upper_bound, 
            verbose, flush_delay,
            normalization,
            func_args, func_kwargs, fixed_params, 
            use_afs, Leff, multinom, ns,
            statistics, pass_Ne,
            output_stream)
        
    p0 = _project_params_down(p0, fixed_params)
    outputs = scipy.optimize.fmin_powell(_object_func_log, np.log(p0), args=args, full_output=True, disp=False)
    
    xopt, fopt, direc, iter, funcalls, warnflag = outputs
    xopt = _project_params_up(np.exp(xopt), fixed_params)
    
    return xopt, fopt


def _project_params_down(pin, fixed_params):
    """
    Eliminate fixed parameters from pin.
    """
    if fixed_params is None:
        return pin

    if len(pin) != len(fixed_params):
        raise ValueError('fixed_params list must have same length as input '
                         'parameter array.')

    pout = []
    for ii, (curr_val,fixed_val) in enumerate(zip(pin, fixed_params)):
        if fixed_val is None:
            pout.append(curr_val)

    return np.array(pout)

def _project_params_up(pin, fixed_params):
    """
    Fold fixed parameters into pin.
    """
    if fixed_params is None:
        return pin

    if np.isscalar(pin):
        pin = [pin]

    pout = np.zeros(len(fixed_params))
    orig_ii = 0
    for out_ii, val in enumerate(fixed_params):
        if val is None:
            pout[out_ii] = pin[orig_ii]
            orig_ii += 1
        else:
            pout[out_ii] = fixed_params[out_ii]
    return pout


