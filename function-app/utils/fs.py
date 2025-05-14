from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=512)
def load_file(file_path: str, check_is_under_path:str = None) -> bytes:
    """
    Load a file from the given path.

    Args:
        file_path (str): The path to the file.
        check_is_under_path (Path, optional): If provided, checks if the file is under this path.

    Returns:
        bytes: The contents of the file as bytes.
    """
    path_to_file = Path(file_path)
    if check_is_under_path is not None:
        check_path = Path(check_is_under_path)
        if not path_to_file.is_relative_to(check_path):
            raise ValueError(f"File {file_path} is not under {check_is_under_path}")
        
        if not path_to_file.is_file():
            raise FileNotFoundError(f"File {file_path} does not exist.")
    
    with open(path_to_file, "rb") as f:
        return f.read()
    

if __name__ == "__main__":
    # Example usage
    try:
        data = load_file("/home/adam/data/ball.png", check_is_under_path="/home/")
        print(data)
    except Exception as e:
        print(e)