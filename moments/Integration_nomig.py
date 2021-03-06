import numpy as np
import scipy as sp
from scipy.sparse import linalg
from . import Reversible
import moments.Spectrum_mod
from . import Numerics
import Jackknife as jk
import LinearSystem_1D as ls1
import LinearSystem_2D as ls2
import Tridiag_solve as ts
from . import Integration
import copy
#------------------------------------------------------------------------------
# Functions for the computation of the Phi-moments for multidimensional models
# without migrations:
# we integrate the ode system on the Phi_n(i) to compute their evolution
# we write it (and solve it) as an approximated linear system:
#       Phi_n' = Bn(N) + (1/(4N)Dn + S1n + S2n)Phi_n
# where :
#       N is the total population size
#       Bn(N) is the mutation source term
#       1/(4N)Dn is the drift effect matrix
#       S1n is the selection matrix for h = 0.5
#       S2n is the effect of h != 0.5
#------------------------------------------------------------------------------

#-----------------------------------
# functions to compute the matrices-
#-----------------------------------

# Mutations
def _calcB(dims, u):
    # u is a list of mutation rates in each population
    # allows for different mutation rates in different pops
    B = np.zeros(dims)
    for k in range(len(dims)):
        ind = np.zeros(len(dims), dtype='int')
        ind[k] = int(1)
        tp = tuple(ind)
        B[tp] = (dims[k] - 1) * u[k]
    return B


# Finite genome mutation model
def _calcB_FB(dims, u, v):
    """
    dims : List containing the pop sizes
    
    u: vectors with the scalar forward mutation rates
    
    v: scalar backward mutation rates
    
    Returns mutation matrix for finite genome model
    
    """
    if len(dims) == 1:
        return ls1.calcB_FB(dims[0], u[0], v[0])
    elif len(dims) == 2: # return list of mutation matrices
        return [ls2.calcB_FB1(dims, u[0], v[0]), ls2.calcB_FB2(dims, u[1], v[1])]
    elif len(dims) == 3:
        return Reversible.calc_FB_3pop(dims, u, v)
    elif len(dims) == 4:
        return Reversible.calc_FB_4pop(dims, u, v)
    elif len(dims) == 5:
        return Reversible.calc_FB_5pop(dims, u, v)

#----------------------------------
# updates for the time integration-
#----------------------------------
# we solve a system like PX = QY
# step 1 functions correspond to the QY computation
# and step 2 to the resolution of PX = Y'

# 2D
# step 1
def _ud1_2pop_1(sfs, Q):
    sfs = Q[0].dot(sfs)
    return sfs

def _ud1_2pop_2(sfs, Q):
    sfs = Q[1].dot(sfs.transpose()).transpose()
    return sfs

# step 2
def _ud2_2pop_1(sfs, slv):
    for i in range(int(sfs.shape[1])):
        sfs[:, i] = slv[0](sfs[:, i])
    return sfs

def _ud2_2pop_2(sfs, slv):
    for i in range(int(sfs.shape[0])):
        sfs[i, :] = slv[1](sfs[i, :])
    return sfs

# for 3D, 4D and 5D cases, each couple of directions are coded separately to simplify the permutations...
#------------------------------
# 3D
# step 1

def _ud1_3pop_1(sfs, Q):
    dims = sfs.shape
    dim2 = np.prod(dims[1::])
    sfs = Q[0].dot(sfs.reshape(dims[0], dim2)).reshape(dims)
    return sfs

def _ud1_3pop_2(sfs, Q):
    Q = [Q[1]]
    sfs = _ud1_3pop_1(np.transpose(sfs, (1, 0, 2)), Q)
    return np.transpose(sfs, (1, 0, 2))

def _ud1_3pop_3(sfs, Q):
    Q = [Q[2]]
    sfs = _ud1_3pop_1(np.transpose(sfs, (2, 1, 0)), Q)
    return np.transpose(sfs, (2, 1, 0))

# step 2
def _ud2_3pop_1(sfs, slv):
    for i in range(int(sfs.shape[2])):
        for j in range(int(sfs.shape[1])):
            sfs[:, j, i] = slv[0](sfs[:, j, i])
    return sfs

def _ud2_3pop_2(sfs, slv):
    for i in range(int(sfs.shape[2])):
        for j in range(int(sfs.shape[0])):
            sfs[j, :, i] = slv[1](sfs[j, :, i])
    return sfs

def _ud2_3pop_3(sfs, slv):
    for i in range(int(sfs.shape[1])):
        for j in range(int(sfs.shape[0])):
            sfs[j, i, :] = slv[2](sfs[j, i, :])
    return sfs

#------------------------------
# 4D
# step 1
def _ud1_4pop_1(sfs, Q):
    return _ud1_3pop_1(sfs, Q)

def _ud1_4pop_2(sfs, Q):
    Q = [Q[1]]
    sfs = _ud1_4pop_1(np.transpose(sfs, (1, 0, 2, 3)), Q)
    return np.transpose(sfs, (1, 0, 2, 3))

def _ud1_4pop_3(sfs, Q):
    Q = [Q[2]]
    sfs = _ud1_4pop_1(np.transpose(sfs, (2, 1, 0, 3)), Q)
    return np.transpose(sfs, (2, 1, 0, 3))

def _ud1_4pop_4(sfs, Q):
    Q = [Q[3]]
    sfs = _ud1_4pop_1(np.transpose(sfs, (3, 1, 2, 0)), Q)
    return np.transpose(sfs, (3, 1, 2, 0))

# step 2
def _ud2_4pop_1(sfs, slv):
    for i in range(int(sfs.shape[1])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                sfs[:, i, j, k] = slv[0](sfs[:, i, j, k])
    return sfs

def _ud2_4pop_2(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                sfs[i, :, j, k] = slv[1](sfs[i, :, j, k])
    return sfs

def _ud2_4pop_3(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[3])):
                sfs[i, j, :, k] = slv[2](sfs[i, j, :, k])
    return sfs

def _ud2_4pop_4(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[2])):
                sfs[i, j, k, :] = slv[3](sfs[i, j, k, :])
    return sfs



#------------------------------
# 5D
# step 1

def _ud1_5pop_1(sfs, Q):
    return _ud1_3pop_1(sfs, Q)

def _ud1_5pop_2(sfs, Q):
    Q = [Q[1]]
    sfs = _ud1_5pop_1(np.transpose(sfs, (1, 0, 2, 3, 4)), Q)
    return np.transpose(sfs, (1, 0, 2, 3, 4))

def _ud1_5pop_3(sfs, Q):
    Q = [Q[2]]
    sfs = _ud1_5pop_1(np.transpose(sfs, (2, 1, 0, 3, 4)), Q)
    return np.transpose(sfs, (2, 1, 0, 3, 4))

def _ud1_5pop_4(sfs, Q):
    Q = [Q[3]]
    sfs = _ud1_5pop_1(np.transpose(sfs, (3, 1, 2, 0, 4)), Q)
    return np.transpose(sfs, (3, 1, 2, 0, 4))

def _ud1_5pop_5(sfs, Q):
    Q = [Q[4]]
    sfs = _ud1_5pop_1(np.transpose(sfs, (4, 1, 2, 3, 0)), Q)
    return np.transpose(sfs, (4, 1, 2, 3, 0))

# step 2
def _ud2_5pop_1(sfs, slv):
    for i in range(int(sfs.shape[1])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                for l in range(int(sfs.shape[4])):
                    sfs[:, i, j, k, l] = slv[0](sfs[:, i, j, k, l])
    return sfs

def _ud2_5pop_2(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                for l in range(int(sfs.shape[4])):
                    sfs[i, :, j, k, l] = slv[1](sfs[i, :, j, k, l])
    return sfs

def _ud2_5pop_3(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[3])):
                for l in range(int(sfs.shape[4])):
                    sfs[i, j, :, k, l] = slv[2](sfs[i, j, :, k, l])
    return sfs

def _ud2_5pop_4(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[2])):
                for l in range(int(sfs.shape[4])):
                    sfs[i, j, k, :, l] = slv[3](sfs[i, j, k, :, l])
    return sfs

def _ud2_5pop_5(sfs, slv):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[2])):
                for l in range(int(sfs.shape[3])):
                    sfs[i, j, k, l, :] = slv[4](sfs[i, j, k, l, :])
    return sfs

# neutral case step 2 (tridiag solver)
# 2D
def _udn2_2pop_1(sfs, A, Di, C):
    for i in range(int(sfs.shape[1])):
        sfs[:, i] = ts.solve(A[0], Di[0], C[0], sfs[:, i])
    return sfs

def _udn2_2pop_2(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        sfs[i, :] = ts.solve(A[1], Di[1], C[1], sfs[i, :])
    return sfs

# 3D
def _udn2_3pop_1(sfs, A, Di, C):
    for i in range(int(sfs.shape[2])):
        for j in range(int(sfs.shape[1])):
            sfs[:, j, i] = ts.solve(A[0], Di[0], C[0], sfs[:, j, i])
    return sfs

def _udn2_3pop_2(sfs, A, Di, C):
    for i in range(int(sfs.shape[2])):
        for j in range(int(sfs.shape[0])):
            sfs[j, :, i] = ts.solve(A[1], Di[1], C[1], sfs[j, :, i])
    return sfs

def _udn2_3pop_3(sfs, A, Di, C):
    for i in range(int(sfs.shape[1])):
        for j in range(int(sfs.shape[0])):
            sfs[j, i, :] = ts.solve(A[2], Di[2], C[2], sfs[j, i, :])
    return sfs

# 4D
def _udn2_4pop_1(sfs, A, Di, C):
    for i in range(int(sfs.shape[1])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                sfs[:, i, j, k] = ts.solve(A[0], Di[0], C[0], sfs[:, i, j, k])
    return sfs

def _udn2_4pop_2(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                sfs[i, :, j, k] = ts.solve(A[1], Di[1], C[1], sfs[i, :, j, k])
    return sfs

def _udn2_4pop_3(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[3])):
                sfs[i, j, :, k] = ts.solve(A[2], Di[2], C[2], sfs[i, j, :, k])
    return sfs

def _udn2_4pop_4(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[2])):
                sfs[i, j, k, :] = ts.solve(A[3], Di[3], C[3], sfs[i, j, k, :])
    return sfs

# 5D
def _udn2_5pop_1(sfs, A, Di, C):
    for i in range(int(sfs.shape[1])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                for l in range(int(sfs.shape[4])):
                    sfs[:, i, j, k, l] = ts.solve(A[0], Di[0], C[0], sfs[:, i, j, k, l])
    return sfs

def _udn2_5pop_2(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[2])):
            for k in range(int(sfs.shape[3])):
                for l in range(int(sfs.shape[4])):
                    sfs[i, :, j, k, l] = ts.solve(A[1], Di[1], C[1], sfs[i, :, j, k, l])
    return sfs

def _udn2_5pop_3(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[3])):
                for l in range(int(sfs.shape[4])):
                    sfs[i, j, :, k, l] = ts.solve(A[2], Di[2], C[2], sfs[i, j, :, k, l])
    return sfs

def _udn2_5pop_4(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[2])):
                for l in range(int(sfs.shape[4])):
                    sfs[i, j, k, :, l] = ts.solve(A[3], Di[3], C[3], sfs[i, j, k, :, l])
    return sfs

def _udn2_5pop_5(sfs, A, Di, C):
    for i in range(int(sfs.shape[0])):
        for j in range(int(sfs.shape[1])):
            for k in range(int(sfs.shape[2])):
                for l in range(int(sfs.shape[3])):
                    sfs[i, j, k, l, :] = ts.solve(A[4], Di[4], C[4], sfs[i, j, k, l, :])
    return sfs

# sfs update 
def _update_step1(sfs, Q):
    assert(len(Q) == len(sfs.shape))
    for i in range(len(sfs.shape)):
        sfs = eval('_ud1_'+str(len(sfs.shape))+'pop_'+str(i+1)+'(sfs, Q)')
    return sfs

def _update_step2(sfs, slv):
    assert(len(slv) == len(sfs.shape))
    for i in range(len(sfs.shape)):
        sfs = eval('_ud2_'+str(len(sfs.shape))+'pop_'+str(i+1)+'(sfs, slv)')
    return sfs

def _update_step2_neutral(sfs, A, Di, C):
    assert(len(A) == len(sfs.shape))
    for i in range(len(sfs.shape)):
        sfs = eval('_udn2_'+str(len(sfs.shape))+'pop_'+str(i+1)+'(sfs, A, Di, C)')
    return sfs




def integrate_nomig(sfs0, Npop, tf, dt_fac=0.1, gamma=None, h=None, theta=1.0, adapt_tstep=False,
                    finite_genome=False, theta_fd=None, theta_bd=None, frozen=[False]):
    """
    Integration in time
    tf : final simulation time (/2N1 generations)
    gamma : selection coefficients (vector gamma = (gamma1,...,gammap))
    theta : mutation rate
    h : allele dominance (vector h = (h1,...,hp))
    m : migration rates matrix (2D array, m[i,j] is the migration rate
      from pop j to pop i, normalized by 1/4N1)

    for a "lambda" definition of N - with backward Euler integration scheme
    where t is the relative time in generations such as t = 0 initially
    Npop is a lambda function of the time t returning the vector N = (N1,...,Np)
      or directly the vector if N does not evolve in time\n
    """
    sfs0 = np.array(sfs0)
    n = np.array(sfs0.shape)-1

    # neutral case if the parameters are not provided
    if gamma is None:
        gamma = np.zeros(len(n))
    if h is None:
        h = 0.5 * np.ones(len(n))
    
    # we convert s and h into numpy arrays 
    if hasattr(gamma, "__len__"):
        s = np.array(gamma)
    else: 
        s = np.array([gamma])
    if hasattr(h, "__len__"):
        h = np.array(h)
    else:
        h = np.array([h])
    
    Tmax = tf * 2.0
    dt = Tmax * dt_fac

    # dimensions of the sfs
    dims = np.array(n + np.ones(len(n)), dtype=int)
    d = int(np.prod(dims))
    
    # if theta is single value, mutation rate is same in each population
    if finite_genome == False:
        if hasattr(theta, "__len__"):
            u = np.array(theta) / 4.0
        else:
            u = np.array([theta / 4.0] * len(dims))
    else:
        if hasattr(theta_fd, "__len__"):
            u = np.array(theta_fd) / 4.0
        else:
            u = np.array([theta_fd/4.] * len(dims))
        if hasattr(theta_bd, "__len__"):
            v = np.array(theta_bd) / 4.0
        else:
            v = np.array([theta_bd/4.] * len(dims))
    
    # if any populations are frozen, we set their population extremely large,
    # selection to zero, and mutations to zero in those pops
    frozen = np.array(frozen)
    if np.any(frozen):
        frozen_pops = np.where(np.array(frozen)==True)[0]
        # fix selection
        for pop_num in frozen_pops:
            s[pop_num] = 0.0
        # fix population sizes
        if callable(Npop):
            nu_func = copy.copy(Npop)
            Npop = lambda t: list( np.array(nu_func(t)) * (1-frozen) + 1e40*frozen )
        else:
            for pop_num in frozen_pops:
                Npop[pop_num] = 1e40
        # fix mutation to zero in frozen populations
        if finite_genome == False:
            u *= (1-frozen)
        else:
            u *= (1-frozen)
            v *= (1-frozen)
            
    # parameters of the equation
    if callable(Npop):
        N = np.array(Npop(0))
    else:
        N = np.array(Npop)
    
    Nold = N.copy()
    # effective pop size for the integration
    Neff = N
    
    # we compute the matrices we will need
    ljk = [jk.calcJK13(int(dims[i] - 1)) for i in range(len(dims))]
    ljk2 = [jk.calcJK23(int(dims[i] - 1)) for i in range(len(dims))]
    
    # drift
    vd = [ls1.calcD(np.array(dims[i])) for i in range(len(dims))]
    D = [1.0 / 4 / N[i] * vd[i] for i in range(len(dims))]
    
    # selection part 1
    vs = [ls1.calcS(dims[i], ljk[i]) for i in range(len(n))]
    S1 = [s[i] * h[i] * vs[i] for i in range(len(n))]

    # selection part 2
    vs2 = [ls1.calcS2(dims[i], ljk2[i]) for i in range(len(n))]
    S2 = [s[i] * (1-2.0*h[i]) * vs2[i] for i in range(len(n))]
    
    # mutations
    if finite_genome == False:
        B = _calcB(dims, u)
    else:
        B = _calcB_FB(dims, u, v)
    
    # time loop:
    t = 0.0
    sfs = sfs0
    while t < Tmax:
        dt_old = dt
        #dt = compute_dt(sfs.shape, N, gamma, h, 0, Tmax * dt_fac)
        dt = min(Integration.compute_dt(N, s=s, h=h), Tmax * dt_fac)
        if t + dt > Tmax:
            dt = Tmax - t

        # we update the value of N if a function was provided as argument
        #if callable(Npop):
        #    N_old = N[:]
        #    N = np.array(Npop((t+dt) / 2.0))
        #    Neff = Numerics.compute_N_effective(Npop, 0.5*t, 0.5*(t+dt))
        #    if np.max(np.abs(N-N_old)/N_old)>0.1: 
        #        print("warning: large change size at time"
        #                + " t = %2.2f in function integrate_nomig" % (t,))
        #        print("N_old, " , N_old)
        #        print("N_new, " , N)
                
                
        if callable(Npop):
            N = np.array(Npop((t+dt) / 2.0))
            Neff = Numerics.compute_N_effective(Npop, 0.5*t, 0.5*(t+dt))
            n_iter_max = 10
            n_iter = 0
            acceptable_change = 0.5
            while (np.max(np.abs(N-Nold)/Nold) > acceptable_change): 
                dt /= 2
                N = np.array(Npop((t+dt) / 2.0))
                Neff = Numerics.compute_N_effective(Npop, 0.5*t, 0.5*(t+dt))
                
                n_iter += 1
                if n_iter >= n_iter_max:
                    #failed to find timestep that kept population shanges in check.
                    print("warning: large change size at time"
                        + " t = %2.2f in function integrate_nomig" % (t,))
                    
                    print("N_old, " , Nold, "N_new", N)
                    print("relative change", np.max(np.abs(N-Nold)/Nold))
                    break
                            
        # we recompute the matrix only if N has changed...
        if t==0.0 or (Nold != N).any() or dt != dt_old:
            D = [1.0 / 4 / Neff[i] * vd[i] for i in range(len(dims))]
            # system inversion for backward scheme
            slv = [linalg.factorized(sp.sparse.identity(S1[i].shape[0], dtype='float', format='csc')
                   - dt/2.0*(D[i]+S1[i]+S2[i])) for i in range(len(n))]
            Q = [sp.sparse.identity(S1[i].shape[0], dtype='float', format='csc')
                 + dt/2.0*(D[i]+S1[i]+S2[i]) for i in range(len(n))]

        # drift, selection and migration (depends on the dimension)
        if len(n) == 1:
            sfs = Q[0].dot(sfs)
            if finite_genome == False:
                sfs = slv[0](sfs + dt*B)
            else:
                sfs = slv[0](sfs + (dt*B).dot(sfs))
        elif len(n) > 1:
            sfs = _update_step1(sfs, Q)
            if finite_genome == False:
                sfs = sfs + dt*B
            else:
                for i in range(len(n)):
                    sfs = sfs + (dt*B[i]).dot(sfs.flatten()).reshape(n+1)
            sfs = _update_step2(sfs, slv)
        Nold = N
        t += dt

    if finite_genome == False:
        return moments.Spectrum_mod.Spectrum(sfs)
    else:
        return moments.Spectrum_mod.Spectrum(sfs, mask_corners=False)


def integrate_neutral(sfs0, Npop, tf, dt_fac=0.1, theta=1.0, adapt_tstep=False, 
                      finite_genome = False, theta_fd=None, theta_bd=None, frozen=[False]):
    """ Integration in time \n
    # tf : final simulation time (/2N1 generations)\n
    # gamma : selection coefficients (vector gamma = (gamma1,...,gammap))\n
    # theta : mutation rate\n
    # h : allele dominance (vector h = (h1,...,hp))\n
    # m : migration rates matrix (2D array, m[i,j] is the migration rate \n
    #   from pop j to pop i, normalized by 1/4N1)\n
    
    # for a "lambda" definition of N - with backward Euler integration scheme\n
    # where t is the relative time in generations such as t = 0 initially\n
    # Npop is a lambda function of the time t returning the vector N = (N1,...,Np)\n
    #   or directly the vector if N does not evolve in time\n
    """
    sfs0 = np.array(sfs0)
    n = np.array(sfs0.shape)-1
    
    Tmax = tf * 2.0
    dt = Tmax * dt_fac
    # dimensions of the sfs
    dims = np.array(n + np.ones(len(n)), dtype=int)
    d = int(np.prod(dims))
    
    # if theta is single value, mutation rate is same in each population
    if finite_genome == False:
        if hasattr(theta, "__len__"):
            u = np.array(theta) / 4.0
        else:
            u = np.array([theta / 4.0] * len(dims))
    else:
        if hasattr(theta_fd, "__len__"):
            u = np.array(theta_fd) / 4.0
        else:
            u = np.array([theta_fd/4.] * len(dims))
        if hasattr(theta_bd, "__len__"):
            v = np.array(theta_bd) / 4.0
        else:
            v = np.array([theta_bd/4.] * len(dims))
    
    # if any populations are frozen, we set their population extremely large,
    # and mutations to zero in those pops
    frozen = np.array(frozen)
    if np.any(frozen):
        frozen_pops = np.where(frozen==True)[0]
        # fix population sizes
        if callable(Npop):
            nu_func = copy.copy(Npop)
            Npop = lambda t: list( np.array(nu_func(t)) * (1-frozen) + 1e40*frozen )
        else:
            for pop_num in frozen_pops:
                Npop[pop_num] = 1e40
        # fix mutation to zero in frozen populations
        if finite_genome == False:
            u *= (1-frozen)
        else:
            u *= (1-frozen)
            v *= (1-frozen)

    # parameters of the equation
    if callable(Npop):
        N = np.array(Npop(0))
    else:
        N = np.array(Npop)

    Nold = N.copy()
    Neff = N

    # drift
    vd = [ls1.calcD_dense(dims[i]) for i in range(len(n))]
    diags = [ts.mat_to_diag(x) for x in vd]
    D = [1.0 / 4 / N[i] * vd[i] for i in range(len(n))]

    # mutations
    if finite_genome == False:
        B = _calcB(dims, u)
    else:
        B = _calcB_FB(dims, u, v)
    
    # time loop:
    t = 0.0
    sfs = sfs0
    while t < Tmax:
        dt_old = dt
        #dt = compute_dt(sfs.shape, N, 0, 0, 0, Tmax * dt_fac)
        dt = min(Integration.compute_dt(N), Tmax * dt_fac)
        if t + dt > Tmax:
            dt = Tmax - t
                
        # we update the value of N if a function was provided as argument
        if callable(Npop):
            N = np.array(Npop((t+dt) / 2.0))
            Neff = Numerics.compute_N_effective(Npop, 0.5*t, 0.5*(t+dt))
            n_iter_max = 10
            n_iter = 0
            acceptable_change = 0.5
            while (np.max(np.abs(N-Nold)/Nold) > acceptable_change): 
                dt /= 2
                N = np.array(Npop((t+dt) / 2.0))
                Neff = Numerics.compute_N_effective(Npop, 0.5*t, 0.5*(t+dt))
                
                n_iter += 1
                if n_iter >= n_iter_max:
                    #failed to find timestep that kept population shanges in check.
                    print("warning: large change size at time"
                        + " t = %2.2f in function integrate_neutral" % (t,))
                    
                    print("N_old, " , Nold, "N_new", N)
                    print("relative change", np.max(np.abs(N-Nold)/Nold))
                    break
              
        # we recompute the matrix only if N has changed...
        if t==0.0 or (Nold != N).any() or dt != dt_old: #SG not sure why dt_old is involved here. 
            D = [1.0 / 4 / Neff[i] * vd[i] for i in range(len(n))]
            A = [-0.5 * dt/ 4 / Neff[i] * diags[i][0] for i in range(len(n))]
            Di = [np.ones(dims[i])-0.5 * dt / 4 / Neff[i] * diags[i][1] for i in range(len(n))]
            C = [-0.5 * dt/ 4 / Neff[i] * diags[i][2] for i in range(len(n))]
            # system inversion for backward scheme
            for i in range(len(n)):
                ts.factor(A[i], Di[i], C[i])
            Q = [np.eye(dims[i]) + 0.5*dt*D[i] for i in range(len(n))]
            
        # drift, selection and migration (depends on the dimension)
        if len(n) == 1:
            if finite_genome == False:
                sfs = ts.solve(A[0], Di[0], C[0], np.dot(Q[0], sfs) + dt*B)
            else:
                sfs = ts.solve(A[0], Di[0], C[0], np.dot(Q[0], sfs) + (dt*B).dot(sfs))
        else:
            sfs = _update_step1(sfs, Q)
            if finite_genome == False:
                sfs = sfs + dt*B
            else:
                for i in range(len(n)):
                    sfs = sfs + (dt*B[i]).dot(sfs.flatten()).reshape(n+1)
            sfs = _update_step2_neutral(sfs, A, Di, C)
        Nold = N
        t += dt

    if finite_genome == False:
        return moments.Spectrum_mod.Spectrum(sfs)
    else:
        return moments.Spectrum_mod.Spectrum(sfs, mask_corners=False)

    return Spectrum_mod.Spectrum(sfs)
