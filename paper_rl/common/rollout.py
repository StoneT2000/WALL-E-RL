import time

import gym
import numpy as np
import torch

from paper_rl.common.buffer import BaseBuffer


class Rollout:
    def __init__(self) -> None:
        pass
    def collect_trajectories(
        self,
        policy,
        env: gym.Env,
        n_trajectories,
        n_envs,
        rollout_callback=None,
        custom_reward=None,
        logger=None,
    ):
        trajectories = []
        past_obs = []
        past_rews = []
        past_acts = []
        for _ in range(n_envs):
            past_obs.append([])
            past_rews.append([])
            past_acts.append([])
        observations = env.reset()
        step = 0
        while True:
            with torch.no_grad():
                acts = policy(observations)
            for idx, o in enumerate(observations):
                past_obs[idx].append(o)
            for idx, a in enumerate(acts):
                past_acts[idx].append(a)

            next_os, rewards, dones, infos = env.step(acts)
            if custom_reward is not None: rewards = custom_reward(rewards, observations, acts)
            for idx, r in enumerate(rewards):
                past_rews[idx].append(r)
            if rollout_callback is not None:
                rollout_callback(
                    observations=observations,
                    next_observations=next_os,
                    actions=acts,
                    rewards=rewards,
                    infos=infos,
                    dones=dones,
                )

            observations = next_os
            # eval_env.render()
            for idx, d in enumerate(dones):
                if d:
                    t_obs = np.vstack(past_obs[idx])
                    t_act = np.vstack(past_acts[idx])
                    t_rew = np.vstack(past_rews[idx])
                    trajectories.append({
                        "observations": t_obs,
                        "rewards": t_rew,
                        "actions": t_act
                    })
                    past_obs[idx] = []
                    past_acts[idx] = []
                    past_rews[idx] = []
                    if len(trajectories) == n_trajectories:
                        return trajectories
            step += 1
    def collect(
        self,
        policy,
        env: gym.Env,
        buf: BaseBuffer,
        steps,
        n_envs,
        rollout_callback=None,
        max_ep_len=1000,
        custom_reward=None,
        logger=None
    ):
        """
        collects for a buffer
        """
        # policy should return a, v, logp
        observations, ep_returns, ep_lengths = env.reset(), np.zeros(n_envs), np.zeros(n_envs)
        rollout_start_time = time.time_ns()
        for t in range(steps):
            a, v, logp = policy(observations)
            next_os, rewards, dones, infos = env.step(a)
            if custom_reward is not None: rewards = custom_reward(rewards, observations, a)
            # for idx, d in enumerate(dones):
            #     ep_returns[idx] += returns[idx]
            ep_returns += rewards
            ep_lengths += 1
            buf.store(observations, a, rewards, v, logp)
            if rollout_callback is not None:
                rollout_callback(
                    observations=observations,
                    next_observations=next_os,
                    actions=a,
                    rewards=rewards,
                    infos=infos,
                    dones=dones,
                )
            if logger is not None: logger.store(tag="train", VVals=v)

            observations = next_os

            timeouts = ep_lengths == max_ep_len
            terminals = dones | timeouts  # terminated means done or reached max ep length
            epoch_ended = t == steps - 1

            for idx, terminal in enumerate(terminals):
                if terminal or epoch_ended:
                    if "terminal_observation" in infos[idx]:
                        o = infos[idx]["terminal_observation"]
                    else:
                        o = observations[idx]
                    ep_ret = ep_returns[idx]
                    ep_len = ep_lengths[idx]
                    timeout = timeouts[idx]
                    if epoch_ended and not terminal:
                        print("Warning: trajectory cut off by epoch at %d steps." % ep_lengths[idx], flush=True)
                    # if trajectory didn't reach terminal state, bootstrap value target
                    if timeout or epoch_ended:
                        _, v, _ = policy(o)
                    else:
                        v = 0
                    buf.finish_path(idx, v)
                    if terminal:
                        # only save EpRet / EpLen if trajectory finished
                        if logger is not None: logger.store("train", EpRet=ep_ret, EpLen=ep_len)
                    ep_returns[idx] = 0
                    ep_lengths[idx] = 0
        rollout_end_time = time.time_ns()
        rollout_delta_time = (rollout_end_time - rollout_start_time) * 1e-9
        if logger is not None: logger.store("train", RolloutTime=rollout_delta_time, append=False)
