import git
import os

# Push updates to GitHub from the deployment repo
def push_updates_to_github(repo_path, deploy_folder_path, files, commit_message):    
    try:
        repo = git.Repo(repo_path)
        
        for file in files:
            # Check if the file_path is relative, convert it to absolute
            if not os.path.isabs(file):
                absolute_file_path = os.path.join(repo_path, deploy_folder_path, file)
            else:
                absolute_file_path = file
            
            # Stage the file for commit
            print(f"Staging {absolute_file_path} for commit...")
            repo.index.add([absolute_file_path])
        
        # Commit the changes
        repo.index.commit(commit_message)
        
        # Push the changes
        repo.remotes.origin.push()
        print("Updates pushed to GitHub.")
    except Exception as e:
        print(f"Error pushing updates to GitHub: {e}")