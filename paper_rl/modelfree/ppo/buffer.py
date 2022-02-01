from typing import Any, Dict, Generator, List, Optional, Union

import numpy as np
import torch
from gym import spaces

from paper_rl.common.buffer import BaseBuffer
from paper_rl.common.mpi.mpi_tools import mpi_statistics_scalar
from paper_rl.common.stats import discount_cumsum


class PPOBuffer(BaseBuffer):
    """
    A buffer for storing trajectories experienced by a PPO agent interacting
    with the environment, and using Generalized Advantage Estimation (GAE-Lambda)
    for calculating the advantages of state-action pairs.
    """

    def __init__(self, observation_space, action_space, size, gamma=0.99, lam=0.95):
        super().__init__(
            buffer_size=size,
            observation_space=observation_space,
            action_space=action_space,
            device=torch.device("cpu"),
            n_envs=1,
        )
        self.obs_buf = np.zeros(size + self.obs_shape, dtype=np.float32)
        self.act_buf = np.zeros((size, self.action_dim), dtype=np.float32)
        self.adv_buf = np.zeros(size, dtype=np.float32)
        self.rew_buf = np.zeros(size, dtype=np.float32)
        self.ret_buf = np.zeros(size, dtype=np.float32)
        self.val_buf = np.zeros(size, dtype=np.float32)
        self.logp_buf = np.zeros(size, dtype=np.float32)
        self.gamma, self.lam = gamma, lam
        self.ptr, self.path_start_idx, self.max_size = 0, 0, size

    def store(self, obs, act, rew, val, logp):
        """
        Append one timestep of agent-environment interaction to the buffer.
        """
        assert self.ptr < self.max_size  # buffer has to have room so you can store
        self.obs_buf[self.ptr] = obs
        self.act_buf[self.ptr] = act
        self.rew_buf[self.ptr] = rew
        self.val_buf[self.ptr] = val
        self.logp_buf[self.ptr] = logp
        self.ptr += 1

    def finish_path(self, last_val=0):
        """
        Call this at the end of a trajectory, or when one gets cut off
        by an epoch ending. This looks back in the buffer to where the
        trajectory started, and uses rewards and value estimates from
        the whole trajectory to compute advantage estimates with GAE-Lambda,
        as well as compute the rewards-to-go for each state, to use as
        the targets for the value function.

        The "last_val" argument should be 0 if the trajectory ended
        because the agent reached a terminal state (died), and otherwise
        should be V(s_T), the value function estimated for the last state.
        This allows us to bootstrap the reward-to-go calculation to account
        for timesteps beyond the arbitrary episode horizon (or epoch cutoff).
        """

        path_slice = slice(self.path_start_idx, self.ptr)
        rews = np.append(self.rew_buf[path_slice], last_val)
        vals = np.append(self.val_buf[path_slice], last_val)

        # the next two lines implement GAE-Lambda advantage calculation
        deltas = rews[:-1] + self.gamma * vals[1:] - vals[:-1]
        self.adv_buf[path_slice] = discount_cumsum(deltas, self.gamma * self.lam)

        # the next line computes rewards-to-go, to be targets for the value function
        self.ret_buf[path_slice] = discount_cumsum(rews, self.gamma)[:-1]

        self.path_start_idx = self.ptr

    def get(self):
        """
        Call this at the end of an epoch to get all of the data from
        the buffer, with advantages appropriately normalized (shifted to have
        mean zero and std one). Also, resets some pointers in the buffer.
        """
        assert self.ptr == self.max_size  # buffer has to be full before you can get
        self.ptr, self.path_start_idx = 0, 0
        # the next two lines implement the advantage normalization trick
        adv_mean, adv_std = mpi_statistics_scalar(self.adv_buf)
        # self.adv_buf = (self.adv_buf - adv_mean) / adv_std
        self.adv_buf = (self.adv_buf - self.adv_buf.mean()) / (self.adv_buf.std())
        data = dict(
            obs=self.obs_buf,
            act=self.act_buf,
            ret=self.ret_buf,
            adv=self.adv_buf,
            logp=self.logp_buf,
        )
        return {k: torch.as_tensor(v, dtype=torch.float32) for k, v in data.items()}



# class PPOBuffer(BaseBuffer):
#     """
#     A buffer for storing trajectories experienced by a PPO agent interacting
#     with the environment, and using Generalized Advantage Estimation (GAE-Lambda)
#     for calculating the advantages of state-action pairs.
#     """

#     def __init__(
#         self,
#         buffer_size: int,
#         observation_space: spaces.Space,
#         action_space: spaces.Space,
#         device: Union[torch.device, str] = "cpu",
#         n_envs: int = 1,
#         gamma=0.99,
#         lam=0.95,
#     ):
#         super().__init__(
#             buffer_size=buffer_size,
#             observation_space=observation_space,
#             action_space=action_space,
#             device=device,
#             n_envs=n_envs,
#         )

#         if isinstance(self.obs_shape, dict):
#             raise NotImplementedError("Can't handle dict observations yet!")

#         self.obs_buf = np.zeros(
#             (self.buffer_size, self.n_envs) + self.obs_shape, dtype=np.float32,
#             # device=self.device
#         )
#         self.act_buf = np.zeros(
#             (self.buffer_size, self.n_envs, self.action_dim), dtype=np.float32,
#             # device=self.device
#         )
#         self.adv_buf = np.zeros((self.buffer_size, self.n_envs), dtype=np.float32,
#         # device=self.device
#         )
#         self.rew_buf = np.zeros((self.buffer_size, self.n_envs), dtype=np.float32, 
#         # device=self.device
#         )
#         self.ret_buf = np.zeros((self.buffer_size, self.n_envs), dtype=np.float32, 
#         # device=self.device
#         )
#         self.val_buf = np.zeros((self.buffer_size, self.n_envs), dtype=np.float32, 
#         # device=self.device
#         )
#         self.logp_buf = np.zeros((self.buffer_size, self.n_envs), dtype=np.float32, 
#         # device=self.device
#         )
#         self.gamma, self.lam = gamma, lam
#         self.ptr, self.path_start_idx, self.max_size = 0, 0, self.buffer_size
#         self.next_batch_idx = 0

#     def store(self, obs, act, rew, val, logp):
#         """
#         Append one timestep of agent-environment interaction to the buffer.
#         """
#         assert self.ptr < self.max_size  # buffer has to have room so you can store
#         self.obs_buf[self.ptr] = np.array(obs).copy()
#         if isinstance(self.action_space, spaces.Discrete):
#             act = act.reshape((self.n_envs, self.action_dim))
#         self.act_buf[self.ptr] = np.array(act).copy()
#         self.rew_buf[self.ptr] = np.array(rew).copy()
#         self.val_buf[self.ptr] = np.array(val).copy()
#         self.logp_buf[self.ptr] = np.array(logp).copy()
#         self.ptr += 1

#     def finish_path(self, env_id, last_val=0):
#         # TODO: remove env_id and do it in batch
#         """
#         Call this at the end of a trajectory, or when one gets cut off
#         by an epoch ending. This looks back in the buffer to where the
#         trajectory started, and uses rewards and value estimates from
#         the whole trajectory to compute advantage estimates with GAE-Lambda,
#         as well as compute the rewards-to-go for each state, to use as
#         the targets for the value function.

#         The "last_val" argument should be 0 if the trajectory ended
#         because the agent reached a terminal state (died), and otherwise
#         should be V(s_T), the value function estimated for the last state.
#         This allows us to bootstrap the reward-to-go calculation to account
#         for timesteps beyond the arbitrary episode horizon (or epoch cutoff).
#         """

#         path_slice = slice(self.path_start_idx, self.ptr)
#         rews = np.append(self.rew_buf[path_slice, env_id], last_val)
#         vals = np.append(self.val_buf[path_slice, env_id], last_val)

#         # the next two lines implement GAE-Lambda advantage calculation
#         deltas = rews[:-1] + self.gamma * vals[1:] - vals[:-1]
#         # print(deltas.shape, self.adv_buf.shape, self.adv_buf[path_slice,env_id].shape)
#         self.adv_buf[path_slice, env_id] = discount_cumsum(deltas, self.gamma * self.lam)

#         # the next line computes rewards-to-go, to be targets for the value function
#         self.ret_buf[path_slice, env_id] = discount_cumsum(rews, self.gamma)[:-1]

#         self.path_start_idx = self.ptr
#     # def sample(self, batch_size):
#     #     self.next_batch_idx: self.next_batch_idx + batch_size
#     # def reset(self):
#     #     self.ptr, self.path_start_idx = 0, 0
#     def get(self):
#         """
#         Call this at the end of an epoch to get all of the data from
#         the buffer, with advantages appropriately normalized (shifted to have
#         mean zero and std one). Also, resets some pointers in the buffer.
#         """
#         assert self.ptr == self.max_size  # buffer has to be full before you can get
#         N = self.buffer_size * self.n_envs
#         self.ptr, self.path_start_idx = 0, 0
#         # the next two lines implement the advantage normalization trick
#         adv_buf = self.adv_buf.reshape(N)
#         adv_buf = (adv_buf - adv_buf.mean()) / (adv_buf.std())

#         data = dict(
#             obs=self.obs_buf.reshape((N, ) + self.obs_shape),
#             act=self.act_buf.reshape((N, self.action_dim)),
#             ret=self.ret_buf.reshape(N),
#             adv=adv_buf.reshape(N),
#             logp=self.logp_buf.reshape(N),
#         )
#         return {k: torch.as_tensor(v, dtype=torch.float32) for k, v in data.items()}