from locate import allow_relative_location_imports
allow_relative_location_imports("../..")

import app_builder
from app_builder import versioned_main
versioned_main.run_versioned_main()
