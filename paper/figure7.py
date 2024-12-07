# General import
import os, sys, argparse
from tqdm import tqdm

# Data import
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, ttest_ind, ttest_1samp
from utils.data import behavior_acc, matching_ranges, cohen_d
from utils.prompt import print_title
from sklearn.linear_model import LinearRegression

# Plot import
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from matplotlib.colors import Normalize
from utils.plots import get_figsize, letter, plot_value_by_iteration, plot_bar_by_gain, plot_by_layer, violinplot_by_gain, barplot_by_layer, plot



def main(args):

    seed = 0
    np.random.seed(seed)

    # -------------------------------
    # Data parameters
    # -------------------------------

    n_max = 18
    scales = np.linspace(1.0, 5.0, 17)
    if args.dataset == 'h':
        tasks = [f'addsub_{n_max}']
    elif args.dataset == 'f':
        tasks =  [f'addsub_{n_max}_font']
    elif args.dataset == 'h+f' or args.dataset == 'f+h':
        tasks = [f'addsub_{n_max}{s}' for s in ['', '_font']]
    task =  '+'.join(tasks)
    steps = np.arange(0, 3801, 100) if args.dataset in ['h', 'f'] else np.arange(0, 7601, 100)
    selected_steps = np.arange(100, 3801, 100)
    selected_steps_idx = np.where(selected_steps[None,:] == steps[:,None])[0]
    ext = f'_fixedbatchnorm'
    idx_roi = 1
    name_roi = 'right IPL/IPS'
    thresholds = [0.95]

    # -------------------------------
    # Figure parameters
    # -----------------------------

    sm = cm.ScalarMappable(norm=Normalize(vmin=0, vmax=1), cmap=cm.get_cmap("coolwarm"))
    c_random = '0.7'
    c_td = sm.to_rgba(0)
    c_md = sm.to_rgba(1)

    zoom = 10
    groups = ['TD', 'MD']
    phi = (1+np.sqrt(5))/2
    ws = phi*np.array([1,1,1])
    wspace = phi
    hs = np.array([1,1])
    hspace = phi

    figsize, _ws, _hs = get_figsize(ws, wspace, hs, hspace, zoom, left = 1.5)

    # -------------------------------
    # Paths where to load/save data
    # -------------------------------

    # Path where accuracy are saved
    accuracy_path = f'{os.environ.get("DATA_PATH")}/{task}/accuracy'
    # Path where model activity are saved
    activity_path = f'{os.environ.get("DATA_PATH")}/{task}/activity'
    # Path containing tuning
    manifold_path = f'{os.environ.get("DATA_PATH")}/{task}/manifold' if args.dataset in ['h', 'f'] else f'{os.environ.get("DATA_PATH")}/{task}/manifold_proj'
    # Path where patient behavior are saved
    behavior_path = f'{os.environ.get("DATA_PATH")}/addsub_{n_max}/behavior'
    # Path where distance between model and patient are saved
    distance_path = f'{os.environ.get("DATA_PATH")}/{task}/distance/accuracy'
    # Path where figure are saved
    figure_path = f'{os.environ.get("FIG_PATH")}/paper/{task}'
    os.makedirs(f'{figure_path}/png', exist_ok=True)
    os.makedirs(f'{figure_path}/pdf', exist_ok=True)

    # -------------------------------
    # Prepare data
    # -------------------------------

    # Patient behavioral data

    patients = pd.read_csv(f'{behavior_path}/TD_MD.csv')
    patient_data = pd.read_csv(f'{os.environ.get("OAK")}/projects/ehk/dnn-modeling-v2/raw/TD_MD_NPs.csv')
    patient_data = patient_data.set_index('PID')
    patient_data = patient_data.reindex(index=patients['PID'].values)
    patient_data = patient_data.reset_index()
    patient_data.rename(columns = {'number_operations_standard:wiat ii':'numops'}, inplace = True)
    patient_data['addsub_accuracy'] = np.nan
    
    for i, p in enumerate(pbar := tqdm(range(patients.shape[0]), leave = False)):
        patient_id = patients["PID"][p]
        patient_group = patients["Group"][p]
        pbar.set_description(f'Processing kid {patient_group} {patient_id:3d}')
        behavior = pd.read_csv(f'{behavior_path}/{patient_id}.csv')
        patient_data.at[i, 'addsub_accuracy'] = behavior_acc(behavior)

    # Model accuracy

    acc = np.empty((len(scales), len(steps)))
    for i, scale in enumerate(tqdm(scales, leave = False)):
        if scale%0.5 == 0:
            accuracy = np.load(f'{accuracy_path}/scaled_{scale:.1f}{ext}/steps_{steps[0]}_{steps[-1]}_accuracy.npy')
        else:
            accuracy = np.load(f'{accuracy_path}/scaled_{scale:.2f}{ext}/steps_{steps[0]}_{steps[-1]}_accuracy.npy')
        idx = np.where(accuracy["step"][:,None] == steps[None, :])[0]
        acc[i] = accuracy["accuracy"][idx]
    acc = acc[:,selected_steps_idx]
    
    # Model manifold properties

    capacity = []
    radius = []
    dimension = []
    correlation = []

    for i,step in enumerate(tqdm(selected_steps)):
        try:
            capacity.append(np.load(f'{manifold_path}/manifold_capacity{ext}_step{step:02}.npz')['arr_0'])
            radius.append(np.load(f'{manifold_path}/manifold_radius{ext}_step{step:02}.npz')['arr_0'])
            dimension.append(np.load(f'{manifold_path}/manifold_dimension{ext}_step{step:02}.npz')['arr_0'])
            correlation.append(np.load(f'{manifold_path}/manifold_correlation{ext}_step{step:02}.npz')['arr_0'])
        except: # TODO: Remove after all done
            print(f'Redo manifold analysis step {step:d}')
            capacity.append(np.nan*capacity[-1])
            radius.append(np.nan*radius[-1])
            dimension.append(np.nan*dimension[-1])
            correlation.append(np.nan*correlation[-1])
    capacity = np.stack(capacity)
    radius = np.stack(radius)
    dimension = np.stack(dimension)
    correlation = np.stack(correlation)

    capacity = (1/np.mean(1/capacity, axis = -1)).T
    radius = np.mean(radius, axis = -1).T
    dimension = np.mean(dimension, axis = -1).T
    correlation = correlation.T

    # Matching

    path = [f'{distance_path}/best_{var}{ext}_numopsv2.npy' for var in ['excitability']+[f"distance{bn}" for bn in ["b"]]]
    best_e_numops = np.load(path[0])
    best_db_numops = np.load(path[1])
    best_step_b_idx = np.argmin(np.sum(best_db_numops, axis = 0))
    best_step_b = steps[best_step_b_idx]
    best_e = best_e_numops[:,best_step_b_idx]
    best_e_idx = np.where(scales[None] == best_e[:,None])[1]
    
    best_step_b_selected_idx = np.where(selected_steps == best_step_b)[0][0]

    capacity_best_e = capacity[:, best_e_idx, best_step_b_selected_idx]
    capacity_best_e_td = np.percentile(capacity_best_e[:,patient_data['Group']=='TD'], q = [5, 50, 95], axis = 1)
    capacity_best_e_md = np.percentile(capacity_best_e[:,patient_data['Group']=='MD'], q = [5, 50, 95], axis = 1)

    dimension_best_e = dimension[:, best_e_idx, best_step_b_selected_idx]
    dimension_best_e_td = np.percentile(dimension_best_e[:,patient_data['Group']=='TD'], q = [5, 50, 95], axis = 1)
    dimension_best_e_md = np.percentile(dimension_best_e[:,patient_data['Group']=='MD'], q = [5, 50, 95], axis = 1)

    correlation_best_e = correlation[:, best_e_idx, best_step_b_selected_idx]
    correlation_best_e_td = np.percentile(correlation_best_e[:,patient_data['Group']=='TD'], q = [5, 50, 95], axis = 1)
    correlation_best_e_md = np.percentile(correlation_best_e[:,patient_data['Group']=='MD'], q = [5, 50, 95], axis = 1)

    # -------------------------------
    # Stats
    # -------------------------------

    print_title('Debug')
    print(f'figsize: {figsize}')
    print(f'capacity shape: {capacity.shape}')

    print_title('Stats')

    modules = ['V1', 'V2', 'V3', 'IPS']
    modules_idx = [0, 2, 6, 8]
    
    for var, name in zip([capacity, dimension, correlation], ['capacity', 'dimension', 'correlation']):
        for m, i in zip(modules, modules_idx):
            print(f'Correlation accuracy with {name} ({m}): {pearsonr(var[i].flatten(), acc.flatten())}')
            if m == 'IPS':
                r,p=pearsonr(var[i].flatten(), acc.flatten())

    for var, name in zip([capacity, dimension, correlation], ['capacity', 'dimension', 'correlation']):
        for m, i in zip(modules, modules_idx):
            X = np.stack([var[i].flatten()], axis = -1)
            y = acc.flatten()
            reg = LinearRegression().fit(X, y)
            print(f'Predictability of accuracy with {name} ({m}) (R2 score): {reg.score(X, y)}')

    for var, name in zip([capacity, dimension, correlation], ['capacity', 'dimension', 'correlation']):
        for m, i in zip(modules, modules_idx):
            r,p = pearsonr(var[i, :, best_step_b_selected_idx], scales)
            step = best_step_b
            print(f'Correlation gain G vs manifold {name} ({m}, iteration {step:d}): (r = {r:.3f}, p = {p:.2e})')

    for i, m in  enumerate(modules):
        t,p = ttest_ind(capacity_best_e[i][patient_data['Group']=='MD'], capacity_best_e[i][patient_data['Group']=='TD'])
        print(f'manifold capacity MD pDNN vs TD pDNN ({m}): (t = {t:.3f}, p = {p:.2e})')
    print(f"Size effect manifold capacity: {cohen_d(capacity_best_e[:,patient_data['Group']=='TD'], capacity_best_e[:,patient_data['Group']=='MD'], axis = 1)[[0,2,6,8]]}")
    for i, m in  enumerate(modules):
        t,p = ttest_ind(dimension_best_e[i][patient_data['Group']=='MD'], dimension_best_e[i][patient_data['Group']=='TD'])
        print(f'manifold dimension MD pDNN vs TD pDNN ({m}): (t = {t:.3f}, p = {p:.2e})')
    print(f"Size effect manifold dimension: {cohen_d(dimension_best_e[:,patient_data['Group']=='TD'], dimension_best_e[:,patient_data['Group']=='MD'], axis = 1)[[0,2,6,8]]}")
    for i, m in  enumerate(modules):
        t,p = ttest_ind(correlation_best_e[i][patient_data['Group']=='MD'], correlation_best_e[i][patient_data['Group']=='TD'])
        print(f'correlation manifold centers MD pDNN vs TD pDNN ({m}): (t = {t:.3f}, p = {p:.2e})')
    print(f"Size effect correlation manifold centers: {cohen_d(correlation_best_e[:,patient_data['Group']=='TD'], correlation_best_e[:,patient_data['Group']=='MD'], axis = 1)[[0,2,6,8]]}")

    # -------------------------------
    # Display
    # -------------------------------
    
    f = plt.figure(figsize = figsize)
    gs = f.add_gridspec(len(hs), len(ws), height_ratios = hs, hspace = hspace/np.mean(hs), width_ratios = ws, wspace = wspace/np.mean(ws), left = _ws[0]/np.sum(_ws), right = 1.0-_ws[-1]/np.sum(_ws), bottom = _hs[-1]/np.sum(_hs), top = 1.0-_hs[0]/np.sum(_hs))
    ax_A = letter('A',plot)(f, gs[0,0], scales, capacity[8,:,best_step_b_selected_idx], xlabel = 'gain $G$', ylabel = 'manifold capacity', ylim = (-0.005, 0.045), xticks = scales[::4], correlate = True)
    ax_B = letter('B',plot)(f, gs[0,1], scales, dimension[8,:,best_step_b_selected_idx], xlabel = 'gain $G$', ylabel = 'manifold dimensionality', ylim = (-1, 201), xticks = scales[::4], correlate = True)
    ax_C = letter('C',plot)(f, gs[0,2], scales, correlation[8,:,best_step_b_selected_idx], xlabel = 'gain $G$', ylabel = 'inter-manifold correlation', ylim = (-0.1, 1.1), xticks = scales[::4], correlate = True)
    ax_D = letter('D', barplot_by_layer)(f, gs[1,0], modules, [capacity_best_e_md[:,modules_idx], capacity_best_e_td[:,modules_idx]], c = [c_md, c_td], label = ['MLD', 'TD'], ylabel = 'manifold capacity')
    ax_E = letter('E', barplot_by_layer)(f, gs[1,1], modules, [dimension_best_e_md[:,modules_idx], dimension_best_e_td[:,modules_idx]], c = [c_md, c_td], label = ['MLD', 'TD'], ylabel = 'manifold dimensionality')
    ax_F = letter('F', barplot_by_layer)(f, gs[1,2], modules, [correlation_best_e_md[:,modules_idx], correlation_best_e_td[:,modules_idx]], c = [c_md, c_td], label = ['MLD', 'TD'], ylabel = 'inter-manifold correlation')

    f.savefig(f'{figure_path}/png/figure7.png', dpi = 1200)
    f.savefig(f'{figure_path}/pdf/figure7.pdf', dpi = 1200)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate Figure 7 of manuscript')
    parser.add_argument('--redo', action='store_true')
    parser.add_argument('--dataset', metavar='D', type = str, default = 'h', choices = ['h', 'f', 'h+f'], help='Which dataset is used to train')
    args = parser.parse_args()
    main(args)
