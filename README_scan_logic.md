# Multi-Level Scanning Logic Documentation

## Overview

The `ScanLogic` module implements a sophisticated hierarchical scanning system that can execute multi-level parameter sweeps with real-time data acquisition and progress tracking. The system supports nested scanning loops where higher-numbered levels (outer loops) change slower than lower-numbered levels (inner loops), enabling complex measurement sequences across multiple instruments.

## Key Features

- **Recursive Multi-Level Scanning**: Supports arbitrary nesting depth with configurable setters and getters
- **Multithreaded Device Communication**: Parallel communication with multiple devices for optimal performance
- **Real-Time Progress Tracking**: Time estimates and completion percentages with GUI updates
- **PyQt6 Signal Integration**: Non-blocking communication with GUI components
- **Artificial Channel Support**: Calculated parameters and derived measurements
- **Manual Pre/Post Settings**: Custom actions before/after each scanning level

## Architecture Overview

```
┌────────────────────────────────────────────────────────────┐
│                    ScanLogic (QThread)                     │
├────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Recursive     │    │  Multithreaded  │                │
│  │   Looping       │◄──►│   Device I/O    │                │
│  │   Algorithm     │    │   Management    │                │
│  └─────────────────┘    └─────────────────┘                │
│           │                       │                        │
│           ▼                       ▼                        │
│  ┌─────────────────┐    ┌─────────────────┐                │
│  │   Data Storage  │    │   Progress      │                │
│  │   & Indexing    │    │   Tracking      │                │
│  └─────────────────┘    └─────────────────┘                │
└────────────────────────────────────────────────────────────┘
                          │
                          ▼
                ┌─────────────────┐
                │   GUI Updates   │
                │   via Qt        │
                │   Signals       │
                └─────────────────┘
```

## Core Concepts

### Level Hierarchy

The scanning system organizes parameters into hierarchical levels:

- **Level 0 (Innermost)**: Changes fastest - fine-resolution parameters like frequency
- **Level 1, 2, ... N**: Change progressively slower - medium-scale parameters like amplitude  
- **Level N (Outermost)**: Changes slowest - major conditions like temperature

### Execution Flow Example

**3-Level Scan**: Temperature [4K, 300K] × Amplitude [0.1V, 0.5V, 1.0V] × Frequency [1Hz, 2Hz, 3Hz, 4Hz, 5Hz]

```
🌡️ Temperature = 4K
├── 🔧 Amplitude = 0.1V
│   ├── 🎵 Freq = 1Hz → 📊 Measure → Store
│   ├── 🎵 Freq = 2Hz → 📊 Measure → Store  
│   └── ... (all 5 frequencies)
├── 🔧 Amplitude = 0.5V
│   └── ... (all 5 frequencies again)
└── 🔧 Amplitude = 1.0V
    └── ... (all 5 frequencies again)

🌡️ Temperature = 300K  
└── ... (repeat all amplitude/frequency combinations)
```

**Total**: 2 × 3 × 5 = 30 measurement points

## Recursive Looping Algorithm

### How Recursive Looping Creates Nested Scans

The scanning system uses a simple recursive function to automatically create nested measurement loops. Here's the high-level flow:

```
                    ┌────────────────────────┐
                    │    Start Scan at       │
                    │   Outermost Level      │
                    └───────────┬────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │   🔧 Setup Phase       │
                    │ • Manual settings       │
                    │ • Group device channels │
                    └───────────┬─────────────┘
                                │
         ┌──────────────────────▼──────────────────────┐
         │             Measurement Loop                │
         │                                             │
         │  For each point at this level:              │
         │  ┌────────────────────────────────────────┐ │
         │  │ 1.  Set device parameters              │ │
         │  │   (multithreaded - all devices at once)│ │
         │  │                                        │ │
         │  │ 2.  Read measurements                  │ │
         │  │   (multithreaded - all devices at once)│ │
         │  │                                        │ │
         │  │ 3. Store data in arrays                │ │
         │  │                                        │ │
         │  │ 4. RECURSIVE CALL                      │ │
         │  │   ↓ Process ALL inner levels           │ │
         │  │   ↓ before moving to next point        │ │
         │  └────────────────────────────────────────┘ │
         └─────────────────────────────────────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │   🧹 Cleanup Phase      │
                    │ • Manual settings       │
                    │ • Reset counters        │
                    └─────────────────────────┘
```



### Why Recursion Works

**Key Insight**: The recursive function call ensures ALL inner measurements complete before the outer level advances to its next point, creating perfect nested loops automatically.

**Example Result**: For Level1=[A,B] and Level0=[1,2,3], measurements occur at: (A,1), (A,2), (A,3), (B,1), (B,2), (B,3)

## Multithreaded Device Communication

### Parallel Write and Read Operations

**The system implements parallel communication for BOTH write and read operations**, enabling simultaneous communication with multiple devices during parameter setting and measurement acquisition.

### How Parallel Communication Works

1. **Device Grouping**: Channels are automatically grouped by device (e.g., `lockin_0`, `nidaq_0`, `nidaq_1`)
2. **ThreadPool**: Creates one thread per device for simultaneous communication
3. **Parallel Execution**: All devices communicate at the same time instead of sequentially

### Performance Benefits

**Sequential**: Write Dev1 → Write Dev2 → Write Dev3 → Read Dev1 → Read Dev2 → Read Dev3
**Parallel**: All devices write simultaneously, then all devices read simultaneously

**Result**: **3-5x faster** for multi-device setups

## Data Storage and Progress Tracking

### Data Organization
- **N-Dimensional Arrays**: Measurement data automatically organized by level hierarchy
- **Real-Time Updates**: Live progress tracking with time estimates
- **GUI Integration**: Non-blocking updates via Qt signals

## Error Handling and Control

### Scan Control
- **Start/Stop**: Responsive start and stop controls
- **Graceful Termination**: Clean shutdown with proper equipment re-initialization  
- **Progress Monitoring**: Real-time time estimates and completion tracking

## System Capabilities

### Performance
- **Multithreaded**: 3-5x speedup through parallel device communication
- **Scalable**: No limit on nesting depth or device count (within hardware constraints)
- **Efficient**: Memory pre-allocation and optimized indexing

### Reliability  
- **Thread-Safe**: Each device operates independently
- **Robust Error Handling**: Graceful recovery from interruptions
- **Real-Time Monitoring**: Live progress and time estimation

This architecture provides a robust, scalable, and high-performance scanning system suitable for complex multi-parameter experimental sequences.