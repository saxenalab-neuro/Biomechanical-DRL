import numpy as np
import time
import argparse
import itertools
import scipy.io
import torch
import matplotlib.pyplot as plt
from tqdm import tqdm
from statistics import mean
from abc import ABC, abstractmethod

class Simulate(object):
    def __init__(self, env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling):
        
        self.env = env
        self.agent = agent
        self.policy_memory = policy_memory
        self.policy_batch_size = policy_batch_size
        self.hidden_size = hidden_size
        self.visualize = visualize
        self.batch_iters = batch_iters
        self.experience_sampling = experience_sampling

        self.policy_loss_tracker = []
        self.critic1_loss_tracker = []
        self.critic2_loss_tracker = []
    
    def _speed_cost(self, timestep):
        timestep_scale = 60
        exp_scale = 0.1
        shift = 3
        timestep_scaled = timestep / timestep_scale
        cost = exp_scale * np.exp(timestep_scaled - shift)
        return cost

    def _step(self, action, timestep, speed_token, episode_reward, episode_steps):
        ### TRACKING REWARD + EXPERIENCE TUPLE###
        next_state, reward, done, info = self.env.step(action)
        next_state = np.append(next_state, speed_token)
        # only works for binary activation of speed penalty
        speed_penalty = self._speed_cost(timestep) * speed_token
        reward -= speed_penalty
        episode_reward += reward
        episode_steps += 1

        return next_state, reward, done, info, episode_reward, episode_steps
    
    def _check_update(self, iteration):
        if iteration % self.experience_sampling == 0 and len(self.policy_memory.buffer) > self.policy_batch_size:
            for _ in tqdm(range(self.batch_iters)):
                critic_1_loss, critic_2_loss, policy_loss = self.agent.update_parameters(self.policy_memory, self.policy_batch_size)
                self.policy_loss_tracker.append(policy_loss)
                self.critic1_loss_tracker.append(critic_1_loss)
                self.critic2_loss_tracker.append(critic_2_loss)
            print(f"mean policy loss: {mean(self.policy_loss_tracker)} | mean critic 1 loss: {mean(self.critic1_loss_tracker)} | mean critic 2 loss: {mean(self.critic2_loss_tracker)}")
    
    @abstractmethod
    def train(self, iteration, speed_token):
        pass

    @abstractmethod
    def test(self, speed_token):
        pass

    
class Simulate_LSTM(Simulate):
    def __init__(self, env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling):
        super(Simulate_LSTM, self).__init__(env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling)

    def train(self, iteration, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        ep_trajectory = []

        #num_layers specified in the policy model 
        h_prev = torch.zeros(size=(1, 1, self.hidden_size))
        c_prev = torch.zeros(size=(1, 1, self.hidden_size))

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action, h_current, c_current, _ = self.agent.select_action(state, h_prev, c_prev, evaluate=False)  # Sample action from policy
            
            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, _, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)

            if self.visualize == True:
                self.env.render()

            mask = 0 if done else 1

            ep_trajectory.append((state, action, np.array([reward]), next_state, np.array([mask]), h_prev.detach().cpu(), c_prev.detach().cpu(), h_current.detach().cpu(),  c_current.detach().cpu()))

            state = next_state
            h_prev = h_current
            c_prev = c_current

            if done and timestep < self.env._max_episode_steps:
                success = 1
            
            ### EARLY TERMINATION OF EPISODE
            if done:
                break

        ### SIMULATION ###
        self._check_update(iteration)
        
        # Push the episode to replay
        self.policy_memory.push(ep_trajectory)

        return episode_reward, episode_steps, success
    
    def test(self, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        #num_layers specified in the policy model 
        h_prev = torch.zeros(size=(1, 1, self.hidden_size))
        c_prev = torch.zeros(size=(1, 1, self.hidden_size))

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action, h_current, c_current, _ = self.agent.select_action(state, h_prev, c_prev, evaluate=True)  # Sample action from policy

            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, info, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)
            episode_reward += reward

            if self.visualize == True:
                self.env.render()

            state = next_state
            h_prev = h_current
            c_prev = c_current

            if done and timestep < self.env._max_episode_steps:
                success = 1

            ### EARLY TERMINATION OF EPISODE
            if done:
                break
        
        return episode_reward, success
        

class Simulate_ANN(Simulate):
    def __init__(self, env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling):
        super(Simulate_ANN, self).__init__(env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling)

    def train(self, iteration, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        ### STEPS PER EPISODE ##from abc import ABC, abstractmethod#
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action = self.agent.select_action(state, evaluate=False)  # Sample action from policy
            
            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, _, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)

            if self.visualize == True:
                self.env.render()

            mask = 0 if done else 1

            self.policy_memory.push([list(state), list(action), reward, list(next_state), mask])

            state = next_state

            if done and timestep < self.env._max_episode_steps:
                success = 1
            
            ### EARLY TERMINATION OF EPISODE
            if done:
                break

        ### SIMULATION ###
        self._check_update(iteration)

        return episode_reward, episode_steps, success
    
    def test(self, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action = self.agent.select_action(state, evaluate=True)  # Sample action from policy

            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, info, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)
            episode_reward += reward

            if self.visualize == True:
                self.env.render()

            state = next_state

            if done and timestep < self.env._max_episode_steps:
                success = 1

            ### EARLY TERMINATION OF EPISODE
            if done:
                break
        
        return episode_reward, success


class Simulate_LSNN(Simulate):
    def __init__(self, env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling):
        super(Simulate_LSNN, self).__init__(env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling)
    
    def _init_lleaky(self):
        mem2_rec = {}
        spk2_rec = {}
        b2_rec = {}
        for name in self.agent.policy.named_children():
            if "lif" in name[0]:
                    spk2_rec[name[0]], mem2_rec[name[0]], b2_rec[name[0]]  = name[1].init_lleaky()
        return spk2_rec, mem2_rec, b2_rec

    def train(self, iteration, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        ep_trajectory = []

        #num_layers specified in the policy model 
        spk2_rec_policy, mem2_rec_policy, b2_rec_policy = self._init_lleaky()

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action, mem2_rec_policy, spk2_rec_policy, b2_rec_policy = self.agent.select_action(state, spk2_rec_policy, mem2_rec_policy, b2_rec_policy, evaluate=False)  # Sample action from policy
            
            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, _, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)

            if self.visualize == True:
                self.env.render()

            if done and timestep < self.env._max_episode_steps:
                success = 1

            mask = 0 if done else 1
            
            ### EARLY TERMINATION OF EPISODE
            if done:
                ep_trajectory.append([state, action, reward, next_state, mask, episode_steps])
                break
            else:
                ep_trajectory.append([state, action, reward, next_state, mask])

            state = next_state

        ### SIMULATION ###
        self._check_update(iteration)

        # Push the episode to replay
        self.policy_memory.push(ep_trajectory)

        return episode_reward, episode_steps, success
    
    def test(self, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        #num_layers specified in the policy model 
        spk2_rec_policy, mem2_rec_policy, b2_rec_policy = self._init_lleaky()

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action, mem2_rec_policy, spk2_rec_policy = self.agent.select_action(state, spk2_rec_policy, mem2_rec_policy, b2_rec_policy, evaluate=True)  # Sample action from policy

            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, info, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)
            episode_reward += reward

            if self.visualize == True:
                self.env.render()

            state = next_state

            if done and timestep < self.env._max_episode_steps:
                success = 1

            ### EARLY TERMINATION OF EPISODE
            if done:
                break
        
        return episode_reward, success


class Simulate_SNN(Simulate):
    def __init__(self, env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling):
        super().__init__(env, agent, policy_memory, policy_batch_size, hidden_size, visualize, batch_iters, experience_sampling)
    
    def _init_leaky(self):
        mem2_rec = {}
        for name in self.agent.policy.named_children():
            if "lif" in name[0]:
                mem2_rec[name[0]] = name[1].init_leaky()
        return mem2_rec

    def train(self, iteration, speed_token):

        done = False
        episode_reward = 0
        episode_steps = 0
        success = 0

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        ep_trajectory = []

        #num_layers specified in the policy model 
        mem2_rec_policy = self._init_leaky()

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action, mem2_rec_policy = self.agent.select_action(state, mem2_rec_policy, evaluate=False)  # Sample action from policy
            
            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, _, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)

            if self.visualize == True:
                self.env.render()

            if done and timestep < self.env._max_episode_steps:
                success = 1

            mask = 0 if done else 1
            
            ### EARLY TERMINATION OF EPISODE
            if done:
                ep_trajectory.append([state, action, reward, next_state, mask, episode_steps])
                break
            else:
                ep_trajectory.append([state, action, reward, next_state, mask])

            state = next_state

        ### SIMULATION ###
        self._check_update(iteration)

        # Push the episode to replay
        self.policy_memory.push(ep_trajectory)

        return episode_reward, episode_steps, success
    
    def test(self, speed_token):

        episode_reward = 0
        episode_steps = 0
        success = 0
        done = False

        ### GET INITAL STATE + RESET MODEL BY POSE
        state = self.env.reset()
        state = np.append(state, speed_token)

        #num_layers specified in the policy model 
        mem2_rec_policy = self._init_leaky()

        ### STEPS PER EPISODE ###
        for timestep in range(self.env._max_episode_steps):

            with torch.no_grad():
                action, mem2_rec_policy = self.agent.select_action(state, mem2_rec_policy, evaluate=True)  # Sample action from policy

            ### TRACKING REWARD + EXPERIENCE TUPLE###
            next_state, reward, done, info, episode_reward, episode_steps = self._step(action, timestep, speed_token, episode_reward, episode_steps)
            episode_reward += reward

            if self.visualize == True:
                self.env.render()

            state = next_state

            if done and timestep < self.env._max_episode_steps:
                success = 1

            ### EARLY TERMINATION OF EPISODE
            if done:
                break
        
        return episode_reward, success