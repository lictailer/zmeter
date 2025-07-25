import time
# import requests  # Commented out - not available in environment
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
import threading


def simulate_io_task(task_id, duration=1):
    """Simulate an I/O bound task like network request or file operation"""
    print(f"Task {task_id} started on thread {threading.current_thread().name}")
    time.sleep(duration)  # Simulate I/O wait
    result = f"Task {task_id} completed"
    print(f"Task {task_id} finished on thread {threading.current_thread().name}")
    return result


def cpu_intensive_task(n):
    """Simulate a CPU-intensive task"""
    print(f"CPU task {n} started on thread {threading.current_thread().name}")
    # Calculate factorial to simulate CPU work
    result = 1
    for i in range(1, n * 1000):
        result = (result * i) % 1000000
    print(f"CPU task {n} finished on thread {threading.current_thread().name}")
    return f"CPU task {n}: {result}"


def simulate_file_operation(file_id, operation_time=1):
    """Simulate file I/O operations"""
    print(f"File operation {file_id} started on thread {threading.current_thread().name}")
    time.sleep(operation_time)  # Simulate file read/write time
    result = f"File {file_id} processed successfully"
    print(f"File operation {file_id} finished on thread {threading.current_thread().name}")
    return result


def demo_io_bound_tasks():
    """Demo with I/O bound tasks - where threading shines"""
    print("=" * 60)
    print("DEMO 1: I/O BOUND TASKS (Network/File operations)")
    print("=" * 60)
    
    tasks = list(range(1, 6))  # 5 tasks
    duration = 2  # 2 seconds each
    
    # Single-threaded execution
    print("\n🐌 Single-threaded execution:")
    start_time = time.time()
    single_results = []
    for task_id in tasks:
        result = simulate_io_task(task_id, duration)
        single_results.append(result)
    single_time = time.time() - start_time
    print(f"Single-threaded time: {single_time:.2f} seconds")
    
    print("\n" + "-" * 40)
    
    # Multi-threaded execution
    print("\n🚀 Multi-threaded execution:")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all tasks at once
        futures = [executor.submit(simulate_io_task, task_id, duration) for task_id in tasks]
        # Collect results
        multi_results = [future.result() for future in concurrent.futures.as_completed(futures)]
    multi_time = time.time() - start_time
    print(f"Multi-threaded time: {multi_time:.2f} seconds")
    
    print(f"\n✨ Time saved: {single_time - multi_time:.2f} seconds")
    print(f"✨ Speed improvement: {single_time / multi_time:.1f}x faster!")


def demo_cpu_bound_tasks():
    """Demo with CPU bound tasks - limited by GIL in Python"""
    print("\n" + "=" * 60)
    print("DEMO 2: CPU BOUND TASKS (Limited by Python's GIL)")
    print("=" * 60)
    
    tasks = [5, 10, 15, 8, 12]  # Different workloads
    
    # Single-threaded execution
    print("\n🐌 Single-threaded execution:")
    start_time = time.time()
    single_results = []
    for task in tasks:
        result = cpu_intensive_task(task)
        single_results.append(result)
    single_time = time.time() - start_time
    print(f"Single-threaded time: {single_time:.2f} seconds")
    
    print("\n" + "-" * 40)
    
    # Multi-threaded execution
    print("\n🚀 Multi-threaded execution:")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(cpu_intensive_task, task) for task in tasks]
        multi_results = [future.result() for future in concurrent.futures.as_completed(futures)]
    multi_time = time.time() - start_time
    print(f"Multi-threaded time: {multi_time:.2f} seconds")
    
    if multi_time < single_time:
        print(f"\n✨ Time saved: {single_time - multi_time:.2f} seconds")
        print(f"✨ Speed improvement: {single_time / multi_time:.1f}x faster!")
    else:
        print(f"\n⚠️  Threading overhead: {multi_time - single_time:.2f} seconds slower")
        print("Note: CPU-bound tasks don't benefit much from threading due to Python's GIL")


def demo_file_operations():
    """Demo with simulated file operations"""
    print("\n" + "=" * 60)
    print("DEMO 3: FILE OPERATIONS")
    print("=" * 60)
    
    files = list(range(1, 6))  # 5 files to process
    operation_time = 1.5  # 1.5 seconds per file
    
    # Single-threaded execution
    print("\n🐌 Single-threaded file processing:")
    start_time = time.time()
    single_results = []
    for file_id in files:
        result = simulate_file_operation(file_id, operation_time)
        single_results.append(result)
        print(f"  {result}")
    single_time = time.time() - start_time
    print(f"Single-threaded time: {single_time:.2f} seconds")
    
    print("\n" + "-" * 40)
    
    # Multi-threaded execution
    print("\n🚀 Multi-threaded file processing:")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(simulate_file_operation, file_id, operation_time) for file_id in files]
        multi_results = []
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            multi_results.append(result)
            print(f"  {result}")
    multi_time = time.time() - start_time
    print(f"Multi-threaded time: {multi_time:.2f} seconds")
    
    print(f"\n✨ Time saved: {single_time - multi_time:.2f} seconds")
    print(f"✨ Speed improvement: {single_time / multi_time:.1f}x faster!")


def advanced_threadpool_features():
    """Show advanced ThreadPoolExecutor features"""
    print("\n" + "=" * 60)
    print("DEMO 4: ADVANCED THREADPOOL FEATURES")
    print("=" * 60)
    
    print("\n📋 Using map() method:")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Map function over multiple inputs
        tasks = [1, 2, 3, 4, 5]
        results = list(executor.map(lambda x: simulate_io_task(x, 0.5), tasks))
        print(f"Map results: {results}")
    map_time = time.time() - start_time
    print(f"Map execution time: {map_time:.2f} seconds")
    
    print("\n🎯 Using submit() with error handling:")
    with ThreadPoolExecutor(max_workers=3) as executor:
        # Submit tasks and handle errors
        futures = []
        for i in range(3):
            if i == 1:  # Simulate an error
                future = executor.submit(lambda: 1/0)  # Division by zero
            else:
                future = executor.submit(simulate_io_task, i, 0.3)
            futures.append(future)
        
        # Process results with error handling
        for i, future in enumerate(futures):
            try:
                result = future.result()
                print(f"  Task {i}: {result}")
            except Exception as e:
                print(f"  Task {i}: ERROR - {str(e)}")


def practical_example():
    """A practical example simulating data processing pipeline"""
    print("\n" + "=" * 60)
    print("DEMO 5: PRACTICAL DATA PROCESSING PIPELINE")
    print("=" * 60)
    
    def process_data_batch(batch_id):
        """Simulate processing a batch of data"""
        print(f"Processing batch {batch_id} on thread {threading.current_thread().name}")
        # Simulate data loading (I/O)
        time.sleep(0.5)
        # Simulate data processing (CPU)
        result = sum(range(batch_id * 1000))
        # Simulate saving results (I/O)
        time.sleep(0.3)
        return f"Batch {batch_id}: processed {result}"
    
    batches = list(range(1, 9))  # 8 batches of data
    
    # Sequential processing
    print("\n🐌 Sequential processing:")
    start_time = time.time()
    for batch in batches:
        result = process_data_batch(batch)
        print(f"  {result}")
    sequential_time = time.time() - start_time
    print(f"Sequential time: {sequential_time:.2f} seconds")
    
    print("\n" + "-" * 40)
    
    # Parallel processing
    print("\n🚀 Parallel processing:")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(process_data_batch, batch) for batch in batches]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            print(f"  {result}")
    parallel_time = time.time() - start_time
    print(f"Parallel time: {parallel_time:.2f} seconds")
    
    print(f"\n✨ Time saved: {sequential_time - parallel_time:.2f} seconds")
    print(f"✨ Speed improvement: {sequential_time / parallel_time:.1f}x faster!")


if __name__ == "__main__":
    print("🧵 ThreadPoolExecutor Demo - Multithreading Performance Analysis")
    print("=" * 70)
    
    # Run all demos
    demo_io_bound_tasks()
    demo_cpu_bound_tasks()
    demo_file_operations()
    advanced_threadpool_features()
    practical_example()
    
    print("\n" + "=" * 70)
    print("🎉 Demo Complete!")
    print("\n📚 Key Takeaways:")
    print("   • Threading excels at I/O-bound tasks (network, file operations)")
    print("   • CPU-bound tasks don't benefit much due to Python's GIL")
    print("   • Use ThreadPoolExecutor for clean, manageable threading")
    print("   • Always handle exceptions when using futures")
    print("   • Consider max_workers based on your specific use case")
    print("   • Best performance gains: 3-5x faster for I/O-bound tasks!")
