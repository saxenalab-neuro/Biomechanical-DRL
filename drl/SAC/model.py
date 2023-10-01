import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Normal
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence, pad_sequence
import numpy as np
import snntorch as snn
from LSNN.lleaky import LLeaky
from LSNN import surrogate

LOG_SIG_MAX = 2
LOG_SIG_MIN = -20
epsilon = 1e-6

# Define Policy SNN Network
class PolicySNN(nn.Module):
    def __init__(self, num_inputs, num_outputs, num_hidden, beta=.95):
        super(PolicySNN, self).__init__()
        self.action_scale = .5
        self.action_bias = .5

        # initialize layers
        self.fc1 = nn.Linear(num_inputs, num_hidden)
        self.lif1 = snn.Leaky(beta=beta)
        self.fc2 = nn.Linear(num_hidden, num_hidden)
        self.lif2 = snn.Leaky(beta=beta)

        self.mean_linear = nn.Linear(num_hidden, num_hidden)
        self.mean_linear_lif = snn.Leaky(beta=beta)
        self.mean_decoder = nn.Linear(num_hidden, num_outputs)

        self.log_std_linear = nn.Linear(num_hidden, num_hidden)
        self.log_std_linear_lif = snn.Leaky(beta=beta)
        self.log_std_decoder = nn.Linear(num_hidden, num_outputs)


    def forward(self, x, mems=None):

        # time-loop
        cur1 = self.fc1(x)
        spk1, mems['lif1'] = self.lif1(cur1, mems['lif1'])
        cur2 = self.fc2(spk1)
        spk2, mems['lif2'] = self.lif2(cur2, mems['lif2'])

        cur_mean = self.mean_linear(spk2)
        spk_mean, mems['mean_linear_lif'] = self.mean_linear_lif(cur_mean, mems['mean_linear_lif'])

        cur_std = self.log_std_linear(spk2)
        spk_std, mems['log_std_linear_lif'] = self.log_std_linear_lif(cur_std, mems['log_std_linear_lif'])

        spk_mean_decoded = self.mean_decoder(spk_mean)
        spk_std_decoded = self.log_std_decoder(spk_std)
        spk_std_decoded = torch.clamp(spk_std_decoded, min=LOG_SIG_MIN, max=LOG_SIG_MAX)

        return spk_mean_decoded, spk_std_decoded, mems
    
    def sample(self, state, sampling, mem=None, training=False):

        if sampling == True:
            state = state.unsqueeze(0)

        spk_mean_decoded, spk_std_decoded, next_mem2_rec = self.forward(state, mems=mem) 

        spk_std_decoded = spk_std_decoded.exp()

        # white noise
        normal = Normal(spk_mean_decoded, spk_std_decoded)
        noise = normal.rsample()

        y_t = torch.tanh(noise) # reparameterization trick
        action = y_t * self.action_scale + self.action_bias
        log_prob = normal.log_prob(noise)
        # Enforce the action_bounds
        log_prob -= torch.log(self.action_scale * (1 - y_t.pow(2)) + epsilon)
        log_prob = log_prob.sum(-1, keepdim=True)
        mean = torch.tanh(spk_mean_decoded) * self.action_scale + self.action_bias

        return action, log_prob, mean, next_mem2_rec


# Define critic SNN Network
class CriticSNN(nn.Module):
    def __init__(self, num_inputs=63, action_space=18, num_hidden=512, beta=.95):
        super(CriticSNN, self).__init__()

        # QNet 1
        self.fc1 = nn.Linear(num_inputs+action_space, num_hidden)
        self.lif1 = snn.Leaky(beta=beta)
        self.fc2 = nn.Linear(num_hidden, num_hidden)
        self.lif2 = snn.Leaky(beta=beta)
        self.output_decoder_1 = nn.Linear(num_hidden, 1)

        # QNet 2
        self.fc1_2 = nn.Linear(num_inputs+action_space, num_hidden)
        self.lif1_2 = snn.Leaky(beta=beta)
        self.fc2_2 = nn.Linear(num_hidden, num_hidden)
        self.lif2_2 = snn.Leaky(beta=beta)
        self.output_decoder_2 = nn.Linear(num_hidden, 1)

    def forward(self, state, action, mem, training=False):

        x = torch.cat([state, action], dim=-1)
    
        #-------------------------------------

        # Q1
        cur1 = self.fc1(x)
        spk1, mem['lif1'] = self.lif1(cur1, mem['lif1'])
        cur2 = self.fc2(spk1)
        spk2, mem['lif2'] = self.lif2(cur2, mem['lif2'])

        # Q Network 1 firing rate 
        q1_decoded = self.output_decoder_1(spk2)

        #---------------------------------------------------------

        # Q2
        cur1 = self.fc1_2(x)
        spk1, mem['lif1_2'] = self.lif1_2(cur1, mem['lif1_2'])
        cur2 = self.fc2_2(spk1)
        spk2, mem['lif2_2'] = self.lif2_2(cur2, mem['lif2_2'])

        q2_decoded = self.output_decoder_2(spk2)

        return q1_decoded, q2_decoded, mem


# Define Policy SNN Network
class PolicyLSNN(nn.Module):
    def __init__(self, num_inputs, num_outputs, num_hidden, beta=.95):
        super(PolicyLSNN, self).__init__()

        self.action_scale = .5
        self.action_bias = .5
        spike_grad = surrogate.custom_surrogate(self._custom_grad)

        # initialize layers
        self.fc1 = nn.Linear(num_inputs, num_hidden)
        nn.init.kaiming_normal_(self.fc1.weight, mode='fan_in')
        self.lif1 = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.fc2 = nn.Linear(num_hidden, num_hidden)
        nn.init.kaiming_normal_(self.fc2.weight, mode='fan_in')
        self.lif2 = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)

        self.mean_linear = nn.Linear(num_hidden, num_hidden)
        nn.init.kaiming_normal_(self.mean_linear.weight, mode='fan_in')
        self.mean_linear_lif = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.mean_decoder = nn.Linear(num_hidden, num_outputs)
        nn.init.kaiming_normal_(self.mean_decoder.weight, mode='fan_in')

        self.log_std_linear = nn.Linear(num_hidden, num_hidden)
        nn.init.kaiming_normal_(self.log_std_linear.weight, mode='fan_in')
        self.log_std_linear_lif = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.log_std_decoder = nn.Linear(num_hidden, num_outputs)
        nn.init.kaiming_normal_(self.log_std_decoder.weight, mode='fan_in')

    def _custom_grad(self, input_, b, grad_input, spikes):
        ## The hyperparameter slope is defined inside the function.
        gamma = 0.3
        normalized = (input_ - b) / b
        grad = gamma * torch.max(torch.zeros_like(normalized), 1 - torch.abs(normalized))
        return grad

    def forward(self, x, spks=None, mems=None, b=None):

        next_mem2_rec = {}
        next_spk2_rec = {}
        next_b2_rec = {}

        # time-loop
        cur1 = self.fc1(x)
        next_spk2_rec['lif1'], next_mem2_rec['lif1'], next_b2_rec['lif1'] = self.lif1(cur1, spks['lif1'], mems['lif1'], b['lif1'])
        cur2 = self.fc2(next_spk2_rec['lif1'])
        next_spk2_rec['lif2'], next_mem2_rec['lif2'], next_b2_rec['lif2'] = self.lif2(cur2, spks['lif2'], mems['lif2'], b['lif2'])

        cur_mean = self.mean_linear(next_spk2_rec['lif2'])
        next_spk2_rec['mean_linear_lif'], next_mem2_rec['mean_linear_lif'], next_b2_rec['mean_linear_lif'] = self.mean_linear_lif(cur_mean, spks['mean_linear_lif'], mems['mean_linear_lif'], b['mean_linear_lif'])

        cur_std = self.log_std_linear(next_spk2_rec['lif2'])
        next_spk2_rec['log_std_linear_lif'], next_mem2_rec['log_std_linear_lif'], next_b2_rec['mean_linear_lif'] = self.log_std_linear_lif(cur_std, spks['log_std_linear_lif'], mems['log_std_linear_lif'], b['mean_linear_lif'])

        spk_mean_decoded = self.mean_decoder(next_spk2_rec['mean_linear_lif'])
        spk_std_decoded = self.log_std_decoder(next_spk2_rec['log_std_linear_lif'])
        spk_std_decoded = torch.clamp(spk_std_decoded, min=LOG_SIG_MIN, max=LOG_SIG_MAX)

        return spk_mean_decoded, spk_std_decoded, next_mem2_rec, next_spk2_rec, next_b2_rec
    
    def sample(self, state, sampling, spks=None, mem=None, b=None, training=False):

        if sampling == True:
            state = state.unsqueeze(0)

        spk_mean_decoded, spk_std_decoded, next_mem2_rec, next_spk2_rec, next_b2_rec = self.forward(state, spks=spks, mems=mem, b=b) 

        spk_std_decoded = spk_std_decoded.exp()

        # white noise
        normal = Normal(spk_mean_decoded, spk_std_decoded)
        noise = normal.rsample()

        y_t = torch.tanh(noise) # reparameterization trick
        action = y_t * self.action_scale + self.action_bias
        log_prob = normal.log_prob(noise)
        # Enforce the action_bounds
        log_prob -= torch.log(self.action_scale * (1 - y_t.pow(2)) + epsilon)
        log_prob = log_prob.sum(-1, keepdim=True)
        mean = torch.tanh(spk_mean_decoded) * self.action_scale + self.action_bias
        
        return action, log_prob, mean, next_mem2_rec, next_spk2_rec, next_b2_rec


# Define critic SNN Network
class CriticLSNN(nn.Module):
    def __init__(self, num_inputs=63, num_outputs=18, num_hidden=512, num_steps=10, beta=.95):
        super(CriticLSNN, self).__init__()
        self.num_steps = num_steps
        spike_grad = surrogate.custom_surrogate(self._custom_grad)
        #spike_grad = surrogate.atan()

        # QNet 1
        self.fc1 = nn.Linear(num_inputs, num_hidden)
        nn.init.kaiming_normal_(self.fc1.weight, mode='fan_in')
        self.lif1 = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.fc2 = nn.Linear(num_hidden, num_hidden)
        nn.init.kaiming_normal_(self.fc2.weight, mode='fan_in')
        self.lif2 = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.output_decoder_1 = nn.Linear(num_hidden, 1)
        nn.init.kaiming_normal_(self.output_decoder_1.weight, mode='fan_in')

        # QNet 2
        self.fc1_2 = nn.Linear(num_inputs, num_hidden)
        nn.init.kaiming_normal_(self.fc1_2.weight, mode='fan_in')
        self.lif1_2 = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.fc2_2 = nn.Linear(num_hidden, num_hidden)
        nn.init.kaiming_normal_(self.fc2_2.weight, mode='fan_in')
        self.lif2_2 = LLeaky(beta=beta, linear_features=num_hidden, spike_grad=spike_grad)
        self.output_decoder_2 = nn.Linear(num_hidden, 1)
        nn.init.kaiming_normal_(self.output_decoder_2.weight, mode='fan_in')

    def _custom_grad(self, input_, b, grad_input, spikes):
        ## The hyperparameter slope is defined inside the function.
        gamma = 0.3
        normalized = (input_ - b) / b
        grad = gamma * torch.max(torch.zeros_like(normalized), 1 - torch.abs(normalized))
        return grad

    def forward(self, state, action, spk, mem, b, training=False):

        x = torch.cat([state, action], dim=-1)
    
        #-------------------------------------

        # Q1
        cur1 = self.fc1(x)
        spk['lif1'], mem['lif1'], b['lif1'] = self.lif1(cur1, spk['lif1'], mem['lif1'], b['lif1'])
        cur2 = self.fc2(spk['lif1'])
        spk['lif2'], mem['lif2'], b['lif2'] = self.lif2(cur2, spk['lif2'], mem['lif2'], b['lif2'])

        # Q Network 1 firing rate 
        q1_decoded = self.output_decoder_1(spk['lif2'])

        #---------------------------------------------------------

        # Q2
        cur1 = self.fc1_2(x)
        spk['lif1_2'], mem['lif1_2'], b['lif1_2'] = self.lif1_2(cur1, spk['lif1_2'], mem['lif1_2'], b['lif1_2'])
        cur2 = self.fc2_2(spk['lif1_2'])
        spk['lif2_2'], mem['lif2_2'], b['lif2_2'] = self.lif2_2(cur2, spk['lif2_2'], mem['lif2_2'], b['lif2_2'])

        q2_decoded = self.output_decoder_2(spk['lif2_2'])

        return q1_decoded, q2_decoded, mem, spk, b
    

class PolicyLSTM(nn.Module):
    def __init__(self, num_inputs, num_actions, hidden_dim, action_space=None):
        super(PolicyLSTM, self).__init__()

        self.linear1 = nn.Linear(num_inputs, hidden_dim)
        nn.init.xavier_normal_(self.linear1.weight)
        self.lstm = nn.LSTM(num_inputs, hidden_dim, num_layers=1, batch_first=True)
        self.linear2 = nn.Linear(2*hidden_dim, hidden_dim)
        nn.init.xavier_normal_(self.linear2.weight)

        self.mean_linear = nn.Linear(hidden_dim, num_actions)
        self.log_std_linear = nn.Linear(hidden_dim, num_actions)

        self.action_scale = torch.tensor(0.5)
        self.action_bias = torch.tensor(0.5)

    def forward(self, state, h_prev, c_prev, sampling):

        if sampling == True:
            fc_branch = F.relu(self.linear1(state))
            lstm_branch, (h_current, c_current) = self.lstm(state, (h_prev, c_prev))
        else:
            state_pad, _ = pad_packed_sequence(state, batch_first= True)
            fc_branch = F.relu(self.linear1(state_pad))
            lstm_branch, (h_current, c_current) = self.lstm(state, (h_prev, c_prev))
            lstm_branch, seq_lens = pad_packed_sequence(lstm_branch, batch_first= True)

        x = torch.cat([fc_branch, lstm_branch], dim=-1)
        x = F.relu(self.linear2(x))
        
        mean = self.mean_linear(x)
        log_std = self.log_std_linear(x)
        log_std = torch.clamp(log_std, min=LOG_SIG_MIN, max=LOG_SIG_MAX)

        return mean, log_std, h_current, c_current, lstm_branch

    def sample(self, state, h_prev, c_prev, sampling):

        mean, log_std, h_current, c_current, lstm_branch = self.forward(state, h_prev, c_prev, sampling)
        #if sampling == False; then reshape mean and log_std from (B, L_max, A) to (B*Lmax, A)

        mean_size = mean.size()
        log_std_size = log_std.size()

        mean = mean.reshape(-1, mean.size()[-1])
        log_std = log_std.reshape(-1, log_std.size()[-1])

        std = log_std.exp()
        normal = Normal(mean, std)
        x_t = normal.rsample()

        y_t = torch.tanh(x_t)
        action = y_t * self.action_scale + self.action_bias

        log_prob = normal.log_prob(x_t)

        # Enforce the action_bounds
        log_prob -= torch.log(self.action_scale * (1 - y_t.pow(2)) + epsilon)
        log_prob = log_prob.sum(1, keepdim=True)

        mean = torch.tanh(mean) * self.action_scale + self.action_bias

        if sampling == False:
            action = action.reshape(mean_size[0], mean_size[1], mean_size[2])
            mean = mean.reshape(mean_size[0], mean_size[1], mean_size[2])
            log_prob = log_prob.reshape(log_std_size[0], log_std_size[1], 1) 

        return action, log_prob, mean, h_current, c_current, lstm_branch
    
    def to(self, device):
        self.action_scale = self.action_scale.to(device)
        self.action_bias = self.action_bias.to(device)
        return super(PolicyLSTM, self).to(device)
    

class CriticLSTM(nn.Module):
    def __init__(self, num_inputs, num_actions, hidden_dim):
        super(CriticLSTM, self).__init__()

        # Q1 architecture
        self.linear1 = nn.Linear(num_inputs + num_actions, hidden_dim)
        nn.init.xavier_normal_(self.linear1.weight)
        self.linear2 = nn.Linear(num_inputs + num_actions, hidden_dim)
        nn.init.xavier_normal_(self.linear2.weight)
        self.lstm1 = nn.LSTM(hidden_dim, hidden_dim, num_layers= 1, batch_first= True)
        self.linear3 = nn.Linear(2 * hidden_dim, hidden_dim)
        nn.init.xavier_normal_(self.linear3.weight)
        self.linear4 = nn.Linear(hidden_dim, 1)
        nn.init.xavier_normal_(self.linear4.weight)

        # Q2 architecture
        self.linear5 = nn.Linear(num_inputs + num_actions, hidden_dim)
        nn.init.xavier_normal_(self.linear5.weight)
        self.linear6 = nn.Linear(num_inputs + num_actions, hidden_dim)
        nn.init.xavier_normal_(self.linear6.weight)
        self.lstm2 = nn.LSTM(hidden_dim, hidden_dim, num_layers= 1, batch_first= True)
        self.linear7 = nn.Linear(2 * hidden_dim, hidden_dim)
        nn.init.xavier_normal_(self.linear7.weight)
        self.linear8 = nn.Linear(hidden_dim, 1)
        nn.init.xavier_normal_(self.linear8.weight)

    def forward(self, state_action_packed, hidden):

        xu = state_action_packed
        xu_p, seq_lens = pad_packed_sequence(xu, batch_first= True)

        fc_branch_1 = F.relu(self.linear1(xu_p))

        lstm_branch_1 = F.relu(self.linear2(xu_p))
        lstm_branch_1 = pack_padded_sequence(lstm_branch_1, seq_lens, batch_first= True, enforce_sorted= False)
        lstm_branch_1, hidden_out_1 = self.lstm1(lstm_branch_1, hidden)
        lstm_branch_1, _ = pad_packed_sequence(lstm_branch_1, batch_first= True)

        x1 = torch.cat([fc_branch_1, lstm_branch_1], dim=-1)
        x1 = F.relu(self.linear3(x1))
        x1 = F.relu(self.linear4(x1))

        fc_branch_2 = F.relu(self.linear5(xu_p))

        lstm_branch_2 = F.relu(self.linear6(xu_p))
        lstm_branch_2 = pack_padded_sequence(lstm_branch_2, seq_lens, batch_first= True, enforce_sorted= False)
        lstm_branch_2, hidden_out_2 = self.lstm2(lstm_branch_2, hidden)
        lstm_branch_2, _ = pad_packed_sequence(lstm_branch_2, batch_first= True)

        x2 = torch.cat([fc_branch_2, lstm_branch_2], dim=-1)
        x2 = F.relu(self.linear7(x2))
        x2 = F.relu(self.linear8(x2))

        return x1, x2
    

# Define Policy SNN Network
class PolicyANN(nn.Module):
    def __init__(self, num_inputs=45, num_outputs=18, num_hidden=512, deterministic=False):
        super(PolicyANN, self).__init__()
        self.deterministic = deterministic
        self.noise = torch.Tensor(num_outputs)
        self.action_scale = .5
        self.action_bias = .5

        # initialize layers
        self.fc1 = nn.Linear(num_inputs, num_hidden)
        self.fc2 = nn.Linear(num_hidden, num_hidden)
        self.fc3 = nn.Linear(num_hidden, num_hidden)
        self.fc4 = nn.Linear(num_hidden, num_hidden)

        self.mean_linear = nn.Linear(num_hidden, num_outputs)
        self.log_std_linear = nn.Linear(num_hidden, num_outputs)

    def forward(self, x):

        # time-loop
        cur1 = self.fc1(x)
        cur2 = self.fc2(cur1)
        cur3 = self.fc3(cur2)
        cur4 = self.fc4(cur3)

        cur_mean = self.mean_linear(cur4)
        cur_std = self.log_std_linear(cur4)
        cur_std = torch.clamp(cur_std, min=LOG_SIG_MIN, max=LOG_SIG_MAX)

        return cur_mean, cur_std
    
    def sample(self, state, sampling, len_seq=None):

        if sampling == True:
            state = state.unsqueeze(0)

        mean, std = self.forward(state) 

        if self.deterministic:
            mean = torch.tanh(mean) * self.action_scale + self.action_bias
            noise = self.noise.normal_(0., std=0.1).to('cuda')
            noise = noise.clamp(-0.25, 0.25)
            action = mean + noise
            return action, torch.tensor(0.), mean

        std = std.exp()
        # white noise
        normal = Normal(mean, std)
        noise = normal.rsample()
        y_t = torch.tanh(noise) # reparameterization trick
        action = y_t * self.action_scale + self.action_bias
        log_prob = normal.log_prob(noise)
        # Enforce the action_bounds
        log_prob -= torch.log(self.action_scale * (1 - y_t.pow(2)) + epsilon)
        log_prob = log_prob.sum(-1, keepdim=True)
        mean = torch.tanh(mean) * self.action_scale + self.action_bias

        return action, log_prob, mean


# Define critic SNN Network
class CriticANN(nn.Module):
    def __init__(self, num_inputs=63, action_space=18, num_hidden=512):
        super(CriticANN, self).__init__()

        # QNet 1
        self.fc1 = nn.Linear(num_inputs + action_space, num_hidden)
        self.fc2 = nn.Linear(num_hidden, num_hidden)
        self.fc3 = nn.Linear(num_hidden, num_hidden)
        self.fc4 = nn.Linear(num_hidden, 1)

        # QNet 2
        self.fc1_2 = nn.Linear(num_inputs + action_space, num_hidden)
        self.fc2_2 = nn.Linear(num_hidden, num_hidden)
        self.fc3_2 = nn.Linear(num_hidden, num_hidden)
        self.fc4_2 = nn.Linear(num_hidden, 1)

    def forward(self, state, action):

        x = torch.cat([state, action], dim=-1)

        out = self.fc1(x)
        out = self.fc2(out)
        out = self.fc3(out)
        q1 = self.fc4(out)

        out = self.fc1_2(x)
        out = self.fc2_2(out)
        out = self.fc3_2(out)
        q2 = self.fc4_2(out)

        return q1, q2