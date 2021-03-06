"""
Single population demographic models.
"""
import numpy

import moments

def snm(ns):
    """
    Standard neutral model.

    ns: Number of samples in resulting Spectrum
    """
    sts = moments.LinearSystem_1D.steady_state_1D(ns[0])
    fs = moments.Spectrum(sts)
    return fs

def two_epoch(params, ns):
    """
    Instantaneous size change some time ago.

    params = (nu,T)
    
    nu: Ratio of contemporary to ancient population size
    T: Time in the past at which size change happened (in units of 2*Na 
       generations) 
    ns: Number of samples in resulting Spectrum.
    """
    nu, T = params
    
    sts = moments.LinearSystem_1D.steady_state_1D(ns[0])
    fs = moments.Spectrum(sts)
    fs.integrate([nu], T)
    return fs

def growth(params, ns):
    """
    Exponential growth beginning some time ago.

    params = (nu,T)

    nu: Ratio of contemporary to ancient population size
    T: Time in the past at which growth began (in units of 2*Na 
       generations) 
    ns: Number of samples in resulting Spectrum.
    """
    nu, T = params

    nu_func = lambda t: [numpy.exp(numpy.log(nu) * t / T)]
    sts = moments.LinearSystem_1D.steady_state_1D(ns[0])
    fs = moments.Spectrum(sts)
    fs.integrate(nu_func, T, 0.01)

    return fs

def bottlegrowth(params, ns):
    """
    Instantanous size change followed by exponential growth.

    params = (nuB,nuF,T)

    nuB: Ratio of population size after instantanous change to ancient
         population size
    nuF: Ratio of contemporary to ancient population size
    T: Time in the past at which instantaneous change happened and growth began
       (in units of 2*Na generations) 
    ns: Number of samples in resulting Spectrum.
    """
    nuB, nuF, T = params
    nu_func = lambda t: [nuB * numpy.exp(numpy.log(nuF/nuB) * t / T)]

    sts = moments.LinearSystem_1D.steady_state_1D(ns[0])
    fs = moments.Spectrum(sts)
    fs.integrate(nu_func, T, 0.01)

    return fs

def three_epoch(params, ns):
    """
    params = (nuB,nuF,TB,TF)

    nuB: Ratio of bottleneck population size to ancient pop size
    nuF: Ratio of contemporary to ancient pop size
    TB: Length of bottleneck (in units of 2*Na generations) 
    TF: Time since bottleneck recovery (in units of 2*Na generations) 

    ns: Number of samples in resulting Spectrum.
    """
    nuB, nuF, TB, TF = params

    sts = moments.LinearSystem_1D.steady_state_1D(ns[0])
    fs = moments.Spectrum(sts)
    fs.integrate([nuB], TB, 0.01)
    fs.integrate([nuF], TF, 0.01)

    return fs
