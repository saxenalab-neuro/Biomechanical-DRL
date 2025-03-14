from SAC.RL_Framework_Mujoco import Muscle_Env    #Muscle_Env is the musculoskeletal environment
from simulate import Simulate
import config
import pdb

def main():

    """ Train an agent to control a musculoskeletal system using DRL and RNNs
        ---------------------------------------------------------------------
    * Simulate object runs training
    * Specify whether testing or not in config file, along with the preferred file to save testing statistics
    * To ensure model is saved properly, specify your preferred directories for storing state_dict
    * A list of possible commands with their functions is given in the config.py file as well as the simulate.py file
    * Specify kinematics by choosing kinematics_path in config file, monkey data is currently provided by default
    """

    ### PARAMETERS ###
    parser = config.config_parser()
    args = parser.parse_args()

    ### TRAINING OBJECT ###
    trainer = Simulate(Muscle_Env, args)

    # trainer = Simulate(
    #     Muscle_Env,
    #     args.model,
    #     args.gamma,
    #     args.tau,
    #     args.lr,
    #     args.alpha,
    #     args.automatic_entropy_tuning,
    #     args.seed,
    #     args.policy_batch_size,
    #     args.hidden_size,
    #     args.policy_replay_size,
    #     args.multi_policy_loss,
    #     args.batch_iters,
    #     args.cuda,
    #     args.visualize,
    #     args.root_dir,
    #     args.checkpoint_file,
    #     args.checkpoint_folder,
    #     args.statistics_folder,
    #     args.total_episodes,
    #     args.load_saved_nets_for_training,
    #     args.save_iter,
    #     args.mode,
    #     args.musculoskeletal_model_path,
    #     args.initial_pose_path,
    #     args.kinematics_path,
    #     args.nusim_data_path,
    #     args.condition_selection_strategy,
    #     args.sim_dt,
    #     args.frame_repeat,
    #     args.n_fixedsteps,
    #     args.timestep_limit,
    #     args.trajectory_scaling,
    #     args.center
    # )

    ### TRAIN OR TEST ###
    if args.mode == "train":
        trainer.train()
    elif args.mode in ["test", "SFE", "sensory_pert", "neural_pert", "musculo_properties"]:
        trainer.test(args.test_data_filename)
    else:
        raise NotImplementedError

if __name__ == '__main__':
    main()
