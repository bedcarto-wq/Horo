from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from horo.time_examples import write_time_examples
write_time_examples(Path(__file__).resolve().parents[1]/'examples')
print('Stage two examples generated in examples/')
