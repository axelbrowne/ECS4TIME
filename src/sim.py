from agent import SoloAgent, NaiveAgent, SensitiveAgent, AdjustAgent
from world import World
from assignment_models import ActionModel, DiscreteModel, RandomModel
from gutil import printProgressBar
from environment import Environment, environment_generator
import plotly.graph_objs as go
import time
from numpy import sqrt, random
import multiprocessing as mp
import pandas as pd
from os import mkdir
import json
from copy import copy

class Sim:
  def __init__(self, environment_dicts, policy, div_node_conf, asr, epsilon, cooling_rate, num_episodes, num_trials, is_community=False, rand_envs=False, node_mutation_chance=0, show=True, save=False, seed=None):
    self.seed = int(random.rand() * 2**32 - 1) if seed is None else seed
    self.rng = random.default_rng(seed)
    self.start_time = time.time()
    self.rand_envs = rand_envs
    self.nmc = node_mutation_chance
    self.environments = [Environment(env_dict) for env_dict in environment_dicts]
    self.num_agents = len(self.environments)
    rand_trials = 0
    if policy == "EF":
      if isinstance(epsilon, (tuple, list, set)):
        rand_trials = [int(num_episodes * eps) for eps in epsilon]
        epsilon = 0
      else:
        rand_trials = int(num_episodes * epsilon)
    self.assignments = {
      "policy": policy,
      "div_node_conf": div_node_conf,
      "asr": asr,
      "epsilon": epsilon,
      "rand_trials": rand_trials,
      "cooling_rate": cooling_rate,
    }
    self.ind_var = self.get_ind_var()
    self.num_episodes = num_episodes
    self.num_trials = num_trials
    self.num_threads = mp.cpu_count()
    self.ass_perms = self.get_assignment_permutations()
    self.is_community = is_community
    self.show = show
    self.save = save
    self.saved_data = pd.DataFrame(index=range(self.num_trials * self.num_episodes))
    self.values = self.get_values(locals())
    
    
  def get_ind_var(self):
    ind_var = None
    for var, assignment in self.assignments.items():
      if isinstance(assignment, (list, tuple, set)):
        assert ind_var is None
        ind_var = var
    return ind_var
  
  def get_assignment_permutations(self):
    if self.ind_var is None:
      return [self.assignments]
    permutations = []
    for ind_var_assignment in self.assignments[self.ind_var]:
      permutation = dict(self.assignments)
      permutation[self.ind_var] = ind_var_assignment
      permutations.append(permutation)
    return permutations
      
  def agent_maker(self, name, environment, databank, assignments):
    policy = assignments.pop("policy")
    if policy == "Solo":
      return SoloAgent(self.rng, name, environment, databank, **assignments)
    elif policy == "Naive":
      return NaiveAgent(self.rng, name, environment, databank, **assignments)
    elif policy == "Sensitive":
      return SensitiveAgent(self.rng, name, environment, databank, **assignments)
    elif policy == "Adjust":
      return AdjustAgent(self.rng, name, environment, databank, **assignments)
    else:
      raise ValueError("Policy type %s is not supported." % policy)
      
  def world_generator(self):
    assignments = [dict(ass) for ass in self.ass_perms for _ in range(int(self.num_agents))]
    if not self.is_community:
      self.rng.shuffle(assignments)
    worlds = []
    for _ in range(len(self.ass_perms)):
      databank = self.environments[0].create_empty_databank()
      envs = environment_generator(self.rng, self.environments[0]._assignment, len(self.environments), self.nmc, self.environments[0].rew_var) if self.rand_envs else self.environments
      agents = [self.agent_maker(str(i), envs[i], databank, assignments.pop()) for i in range(self.num_agents)]
      worlds.append(World(agents, self.is_community))
    return worlds
  
  def multithreaded_sim(self):
    jobs = []
    results = mp.Manager().list([None] * self.num_threads)
    for i in range(self.num_threads):
      job = mp.Process(target=self.simulate, args=(results, i))
      jobs.append(job)
      job.start()
    [job.join() for job in jobs]
    return results
  
  def simulate(self, results, index):
    trial_result = {}
    for i in range(self.num_trials):
      worlds = self.world_generator()
      for j, world in enumerate(worlds):
        for k in range(self.num_episodes - 1):
          world.run_once()
          printProgressBar(i*len(worlds)+j+(k+1)/(self.num_episodes - 1), self.num_trials * len(worlds))
        self.update_trial_result(trial_result, world)
    results[index] = trial_result
  
  def update_trial_result(self, trial_result, world):
    raw = world.pseudo_cum_regret
    if self.is_community:
      ind_var = world.agents[0].get_ind_var_value(self.ind_var)
      result = pd.DataFrame(data=[pd.DataFrame(data=raw.values()).sum(axis=0)], columns=range(self.num_episodes))
      if ind_var not in trial_result:
        trial_result[ind_var] = result
        return
      trial_result[ind_var] = trial_result[ind_var].append(result, ignore_index=True)
      return
    for agent, data in raw.items():
      ind_var = agent.get_ind_var_value(self.ind_var)
      result = pd.DataFrame(data=[data], columns=range(self.num_episodes))
      if ind_var not in trial_result:
        trial_result[ind_var] = result
        continue
      trial_result[ind_var] = trial_result[ind_var].append(result, ignore_index=True)
      
  
  def combine_results(self, trial_results):
    results = {}
    for trial_result in trial_results:
      for ind_var, df in trial_result.items():
        if ind_var not in results:
          results[ind_var] = df
          continue
        results[ind_var] = results[ind_var].append(df, ignore_index=True)
    return results
  
  def get_plot(self, results, plot_title):
    figure = []
    x = list(range(self.num_episodes))
    for i, ind_var in enumerate(sorted(results)):
      line_hue = str(int(360 * (i / len(results))))
      df = results[ind_var]
      y = df.mean(axis=0)
      sqrt_variance = sqrt(df.var(axis=0))
      y_upper = y + sqrt_variance
      y_lower = y - sqrt_variance
      line_color = "hsla(" + line_hue + ",100%,50%,1)"
      error_band_color = "hsla(" + line_hue + ",100%,50%,0.125)"
      figure.extend([
      go.Scatter(
        name=ind_var,
        x=x,
        y=y,
        line=dict(color=line_color),
        mode='lines',
      ),
      go.Scatter(
        name=ind_var+"-upper",
          x=x,
          y=y_upper,
          mode='lines',
          marker=dict(color=error_band_color),
          line=dict(width=0),
          # showlegend=False,
      ),
      go.Scatter(
          name=ind_var+"-lower",
          x=x,
          y=y_lower,
          marker=dict(color=error_band_color),
          line=dict(width=0),
          mode='lines',
          fillcolor=error_band_color,
          fill='tonexty',
          # showlegend=False,
      )
    ])
    plotly_fig = go.Figure(figure)
    plotly_fig.update_layout(
      yaxis_title="Pseudo Cumulative Regret",
      xaxis_title="Episodes",
      title=plot_title,
    )
    return plotly_fig
    
  def display_and_save(self, plot, plot_title):
    elapsed_time = time.time() - self.start_time
    print("\nTime elapsed: {:02d}:{:02d}:{:05.2f}".format(
      int(elapsed_time // (60 * 60)),
      int((elapsed_time // 60)),
      elapsed_time % 60
    ))
    print("Seed: %d" % self.seed)
    N = self.get_N()
    print("N=%d" % N)
    if self.show:
      plot.show()
    if self.save:
      date = time.strftime("%m%d", time.gmtime())
      file_name = "{}_E{}_N{}_{}".format(date, self.num_episodes, N, plot_title)
      dir_path = "../output/%s" % file_name
      mkdir(dir_path)
      plot.write_html(dir_path + "/plot.html")
      self.saved_data.to_csv(dir_path + "/last_episode_data.csv")
      with open(dir_path + '/values.json', 'w') as outfile:
        json.dump(self.values, outfile)
      
  def run(self, plot_title=""):
    results = self.combine_results(self.multithreaded_sim())
    self.display_and_save(self.get_plot(results, plot_title), plot_title)
    
  def get_N(self):
    if self.is_community:
      return self.num_threads * self.num_trials
    return self.num_threads * self.num_trials * self.num_agents
  
  def get_values(self, locals):
    values = {key: val for key, val in locals.items() if key != 'self'}
    parsed_env_dicts = []
    for env in values["environment_dicts"]:
      parsed_env = {}
      for node, model in env.items():
        parsed_env[node] = str(model)
      parsed_env_dicts.append(parsed_env)
    values["environment_dicts"] = tuple(parsed_env_dicts)
    return values

if __name__ == "__main__":
  baseline = {
    "W": RandomModel((0.4, 0.6)),
    "X": ActionModel(("W"), (0, 1)),
    "Z": DiscreteModel(("X"), {(0,): (0.75, 0.25), (1,): (0.25, 0.75)}),
    "Y": DiscreteModel(("W", "Z"), {(0, 0): (1, 0), (0, 1): (1, 0), (1, 0): (1, 0), (1, 1): (0, 1)})
  }
  w1 = dict(baseline)
  w1["W"] = RandomModel((0.1, 0.9))
  w9 = dict(baseline)
  w9["W"] = RandomModel((0.9, 0.1))
  z5 = dict(baseline)
  z5["Z"] = DiscreteModel(("X"), {(0,): (0.9, 0.1), (1,): (0.5, 0.5)})
  reversed_z = dict(baseline)
  reversed_z["Z"] = DiscreteModel(("X"), {(0,): (0.25, 0.75), (1,): (0.75, 0.25)})
  reversed_y = dict(baseline)
  reversed_y["Y"] = DiscreteModel(("W", "Z"), {(0, 0): (0, 1), (0, 1): (1, 0), (1, 0): (1, 0), (1, 1): (1, 0)})

  envs = [e._assignment for e in environment_generator(random.default_rng(), baseline, 4, 0.166667, "Y")]

  experiment = Sim(
    environment_dicts=tuple(envs),
    policy=("Solo", "Naive", "Sensitive", "Adjust"), 
    asr="ED",
    epsilon=1,
    cooling_rate=0.076,
    div_node_conf=0.04, 
    num_episodes=75,
    num_trials=1,
    is_community=False,
    rand_envs=True,
    node_mutation_chance=0.2,
    show=True,
    save=False,
    seed=None
  )
  experiment.run(plot_title="CPR of Individual Agents using Epsilon Decreasing ASR (Epsilon-1, Cooling Rate=0.076)")
