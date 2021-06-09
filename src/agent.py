# from causal_graph import CausalGraph
from knowledge import Knowledge
import util
import gutil
import random
from enums import Datatype, Policy

DIV_NODE_CONF = 0.055
SAMPS_NEEDED = 15
DIV_EPS_DEC_SLOWNESS = 2

class Agent:
  def __init__(self, name, environment, epsilon=0.05, policy=Policy.DEAF):
    self.name = name
    self.environment = environment
    self.reward_var = self.environment.reward_node
    self.epsilon = epsilon
    self.policy = policy
    self.friends = {}
    self.action_nodes = self.environment.action_nodes
    self.knowledge = Knowledge(self.environment)
    self.action_domains = gutil.only_given_keys(self.environment.domains, self.action_nodes)
    self.friend_divergence = {}
    # self.recent = None

  def act(self):
    givens = self.environment.pre.sample()
    choice = self.choose(givens)
    givens |= choice[1]
    # env_act_feedback = self.environment.post.sample(givens)
    self.knowledge.add_sample(self.environment.post.sample(givens))
    # self.knowledge.add_obs(env_act_feedback) \
    #     if choice[0] == Datatype.OBS \
    #     else self.knowledge.add_exp(env_act_feedback)
    # self.recent = env_act_feedback

  def choose(self, givens={}):
    if random.random() < self.epsilon:
      return (Datatype.EXP, self.experiment(givens))
    else:
      optimal_choice = self.optimal_choice(givens)
      return (Datatype.OBS, optimal_choice) if optimal_choice else (Datatype.EXP, self.experiment(givens))

  def experiment(self, givens={}):
    reward_vals = util.reward_vals(
      self.knowledge.get_useful_data(), self.action_nodes, self.reward_var, givens)
    unexplored = [util.dict_from_hash(e) for e in util.hashes_from_domain(self.action_domains) if e not in reward_vals.keys()]
    return random.choice(unexplored) if unexplored\
      else self.random_action()

  def optimal_choice(self, givens={}):
    my_data = self.knowledge.samples.copy()
    
    if self.policy == Policy.NAIVE:
      for f in self.friends:
        my_data.extend(self.friends[f])
    
    if self.policy == Policy.SENSITIVE:
      for f in self.friends:
        if True not in self.friend_divergence[f].values():
          my_data.extend(self.friends[f])
    
    expected_values = util.expected_vals(
        my_data, self.action_nodes, self.reward_var, givens)
    return util.dict_from_hash(gutil.max_key(expected_values)) if expected_values\
      else self.random_action()

  def random_action(self):
    return random.choice(gutil.permutations(self.action_domains))

  def add_friend(self, other):
    self.friends[other.name] = []
    self.friend_divergence[other.name] = {}
    for node in self.knowledge.model.get_observable():
      if node in self.action_nodes: continue
      self.friend_divergence[other.name][node] = True

  def encounter(self, other):
    if self.policy == Policy.DEAF: return
    # friend_data = other.recent#other.knowledge.get_useful_data()
    if other.name not in self.friends:
      self.add_friend(other)
    other_recent = other.get_data()[-1]
    if other_recent:
      self.friends[other.name].append(other_recent)
    if self.policy == Policy.SENSITIVE:
      self.update_friend_divergence()
    
  def get_data(self):
    return self.knowledge.samples

  # def divergences_from_friends(self):
  #   divergences = {}
  #   for agent in self.friends:
  #     divergences[agent] = self.divergence_from_other(self.friends[agent])
  #   return divergences

  # def divergence_from_other(self, other_data):
  #   divergence = {}
  #   for node in self.knowledge.model.get_observable():
  #     if node in self.action_nodes: continue
  #     divergence[node] = self.knowledge.kl_divergence_of_node(node, other_data)
  #   return divergence

  def update_friend_divergence(self):
    for f in self.friends:
      friend_data = self.friends[f]
      div_epsilon = (SAMPS_NEEDED * DIV_EPS_DEC_SLOWNESS)/(len(friend_data) - SAMPS_NEEDED + SAMPS_NEEDED * DIV_EPS_DEC_SLOWNESS)
      if div_epsilon > 1: continue
      for node in self.friend_divergence[f]:
        if self.friend_divergence[f][node] == False:
          if random.random() >= div_epsilon:
            continue
        node_div = self.knowledge.kl_divergence_of_node(node, friend_data)
        if node_div != None and node_div < DIV_NODE_CONF:
          self.friend_divergence[f][node] = False
        # else:
        #   break
    return

  def __hash__(self):
    return hash(self.name)

  def __eq__(self, other):
    return self.__class__ == other.__class__ and self.name == other.name and self.environment == other.environment and self.reward_var == other.reward_var