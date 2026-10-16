from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from horo.physics_examples import write_examples
write_examples(Path(__file__).resolve().parents[1]/'examples')
