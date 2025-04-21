# Changelog

All notable changes will be documented in this file.

## [2025-04-21] - UI Improvements
### Changed
- Refactored ingress length for better readability
- Improved date formatting in UI components
- Enhanced responsiveness to window zoom/resize

### Fixed
- Bullet point layout rendering issues

### Added
- Price data backdrop for wind power chart for better context
- Pyhäpäivä (Finnish holiday) fallback option

### Removed
- Smoothing/ramping functionality for cleaner predictions

## [2025-03-15] - Prompt Engineering
### Changed
- Refined LLM prompts for better narration quality

## [2025-02-23] - Archiving and Logging
### Added
- Archive feature for prediction history
- Helper for tomorrow prices
- Environment variable management for paths

### Changed
- Improved logging and archiving system

## [2025-02-07] - English Version
### Added
- English language version of the interface
- Documentation for environment variables

### Changed
- Refined prompt tuning for better text generation

## [2025-01-19] - Hourly Data and Visualization
### Added
- Ramp smoothing for price predictions
- Hourly data with spike risk narration
- DeepSeek LLM support for text generation
- Wind power as percentage of max capacity

### Changed
- Adjusted hyperparameters for better predictions
- Improved handling of outliers

### Fixed
- Ensured latest weather station data before training

## [2025-01-18] - Data Source Improvements
### Added
- Fingrid data downloader
- Documentation for recent changes

### Changed
- Renamed components for clarity
- Improved logging

## [2025-01-15] - Baltic Wind Integration
### Added
- Baltic wind speeds data integration
- Enhanced hyperparameter history logging

### Changed
- Relocated training statistics
- Improved code organization and cleanup

## [2025-01-12] - Baltic Sea Region Wind
### Added
- Baltic Sea region wind speeds as prediction features
- Documentation for environmental variables

### Fixed
- Unit and span issues in visualizations

## [2025-01-11] - Data Handling
### Added
- Better management of missing input data
- Handling for erroneous inputs

### Changed
- Fine-tuned hyperparameters

## [2025-01-05] - Feature Expansion
### Added
- Individual border flows
- Solar irradiance data source
- 7-day forecast capabilities
- Wind power on-demand model training
- Holiday data set
- Direct SQL integration
- Local hosting options

### Changed
- Styling improvements
- Data source organization

## [2024-12-25] - Holiday Integration and History
### Added
- Holiday data and narration
- Extended snapshot history to 30 days
- Snapshot pruning for better management

### Changed
- Wind power axis maximum to 8 GW
- Improved timestamp consolidation
- Exception handling enhancements

## [2024-12-21] - Wind Power Training
### Added
- Wind power live training capability
- Tornio weather station (101851) support

### Changed
- Wind power hyperparameters optimization
- Removed offline training for wind power

## [2024-12-19] - Weather Station Improvements
### Added
- Weather station filtering from environment variables

### Changed
- Documentation update for FMISID 101799 (no longer available)

## [2024-12-07] - Neural Network Model
### Added
- Neural network model for wind power prediction

### Changed
- Model relocation for better organization

### Fixed
- Prompt tags in text generation

## [2024-11-20] - Nuclear and VAT Updates
### Added
- Support for unplanned nuclear outages

### Fixed
- VAT multiplier calculation

## [2024-11-10] - JAO Integration
### Added
- JAO import capacity support
- Price data as table view

### Changed
- Integration of training into predict command
- Removed deprecated statistical features

## [2024-11-02] - Data Integrity
### Added
- Sanity checks for Fingrid data

### Fixed
- Timezone handling for averages.json
- Missing outage data handling

## [2024-10-28] - Narration Updates
### Added
- Narration as JSON for Home Assistant

## [2024-10-27] - Wind Power Narration
### Added
- Wind power min/max narration

## [2024-10-20] - LLM Narration Expansion
### Added
- LLM narration for import data
- Nuclear/transmission outages JSON
- LLM narration on nuclear/transmission outages

## [2024-10-19] - Visualization
### Added
- Bar chart visualization

## [2024-10-17] - Data Validation
### Added
- ENTSO-E sanity checks

## [2024-10-15] - Model Improvements
### Added
- Early stopping for XGBoost models
- Gap interpolation for better predictions

### Changed
- Made --predict require model training in memory

## [2024-10-06] - Feature Enhancement
### Fixed
- Feature matching issues

### Added
- Year as a feature for predictions

## [2024-09-29] - Temperature Features
### Added
- Temperature narration
- Temperature mean/variance as columns

### Changed
- Model tuning improvements
- Fill method updates

## [2024-09-22] - Wind Power Integration
### Added
- Planned imports for wind power prediction
- Narration with wind power information

## [2024-09-18] - Wind Power Prediction
### Added
- Wind power prediction chart
- Wind power prediction model
- Wind power and main model training scripts

### Changed
- Updated VAT handling to allow for variation

## [2024-09-08] - Bug Fixes
### Fixed
- Inline styles issues
- Prediction snapshots corruption

## [2024-09-01] - Model Tuning
### Changed
- Wind power experiments and prediction
- XGBoost tuning and optimization
- Renamed utilities for clarity
- Logging format improvements

## [2024-08-31] - Model Transition
### Changed
- Switched from Random Forest to XGBoost
- Grid search tuning for hyperparameters

## [2024-08-19] - Import Capacity
### Added
- Import capacity for SE1, SE3, EE regions
- Documentation for transfer capacity

### Fixed
- ENTSO-E OL3 data issues

## [2024-06-22] - Dynamic Date Formatting
### Added
- Dynamic date formatting

## [2024-05-26] - Finnish Formatting
### Added
- Finnish formatting for prediction chart dates and weekdays

## [2024-04-20] - Error Handling
### Added
- Error handling for ENTSO-E downtime

### Changed
- Moved GitHub push functionality outside main script

## [2024-03-07] - Optimization
### Added
- Hyperparameter optimization
- ENTSO-E downtime messages for nuclear

### Changed
- Cleanup and deprecation of obsolete features

## [2024-03-03] - Model Evaluation
### Added
- Feature importance metrics
- Durbin-Watson and autocorrelation tests
- Daily prediction snapshots as JSON

## [2024-03-02] - Data Management
### Added
- Documentation on adding new models and data sources
- Proper backfilling with last known values

## [2024-03-01] - Deployment
### Changed
- Renamed --publish to --deploy for clarity
- Significant codebase cleanup

### Added
- Database dump functionality

## [2024-02-29] - FMI Integration
### Added
- FMI-based modeling
- Switch to FMISID for accurate location identification

## [2024-02-27] - Documentation and Metrics
### Added
- Wind power forecast
- Improved descriptions
- Documentation on local setup
- Evaluation metrics

## [2024-02-26] - Nuclear Power
### Added
- Nuclear power production as a data point

## [2024-02-25] - UI Improvements
### Added
- New domain setup
- Layout improvements
- "Now" marker for current time

## [2024-02-24] - Visualization
### Added
- eCharts visualization
- Continuous training

## [2024-02-23] - Initial Release
### Added
- Initial commit