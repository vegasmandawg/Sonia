// services/apiQueueService.ts

const MAX_RETRIES = 3;
const INITIAL_BACKOFF_MS = 1500; // Start with a slightly longer wait

interface QueuedRequest<T> {
  requestFn: () => Promise<T>;
  resolve: (value: T | PromiseLike<T>) => void;
  reject: (reason?: any) => void;
  retries: number;
}

const queue: QueuedRequest<any>[] = [];
let isProcessing = false;

/**
 * Checks if a given error is a Gemini API rate limit error (429).
 * It handles errors that are objects or stringified JSON.
 * @param error The error object to check.
 * @returns True if it's a rate limit error, false otherwise.
 */
const isRateLimitError = (error: any): boolean => {
    try {
        let errorDetails = error;
        if (typeof errorDetails === 'string') {
             try {
                errorDetails = JSON.parse(errorDetails);
            } catch (e) {
                // If it's not valid JSON, it's not the structured error we're looking for.
                return false;
            }
        }
        
        return errorDetails?.error?.code === 429;
    } catch (e) {
        return false;
    }
};

/**
 * Checks if the error is a permanent quota issue (limit: 0), which cannot be solved by retrying.
 * @param error The error object to check.
 * @returns True if it's a permanent quota error.
 */
const isPermanentQuotaError = (error: any): boolean => {
    try {
        let errorMessage = '';
        let errorDetails = error;
        if (typeof errorDetails === 'string') {
             try {
                errorDetails = JSON.parse(errorDetails);
            } catch {
                // Not JSON, continue to check raw string
            }
        }
        
        errorMessage = errorDetails?.error?.message || (typeof error === 'string' ? error : '');

        // The key indicator of a billing/setup issue vs. a transient rate limit
        return errorMessage.includes('limit: 0');
    } catch {
        return false;
    }
};

const processQueue = async () => {
  if (isProcessing || queue.length === 0) {
    isProcessing = false;
    return;
  }
  isProcessing = true;

  const { requestFn, resolve, reject, retries } = queue.shift()!;

  try {
    const result = await requestFn();
    resolve(result);
    // Move to the next item
    isProcessing = false;
    processQueue();
  } catch (error: any) {
    console.error(`API request failed (Attempt ${retries + 1}):`, error);
    
    if (isPermanentQuotaError(error)) {
        console.error("Permanent quota error detected. Aborting retries.");
        const specificError = new Error(
            "API request failed: Your API key has a quota of 0 requests. Please check your Google Cloud project's billing status and ensure the Generative Language API is enabled. Retrying will not solve this issue."
        );
        reject(specificError);
        isProcessing = false;
        processQueue(); // Continue with next item in queue
        return;
    }
    
    if (isRateLimitError(error) && retries < MAX_RETRIES) {
      const backoffTime = INITIAL_BACKOFF_MS * Math.pow(2, retries);
      console.warn(`Rate limit hit. Retrying in ${backoffTime}ms...`);
      
      // Stop processing and wait for the backoff period
      isProcessing = false;
      setTimeout(() => {
        // Re-queue the request at the front with an increased retry count
        queue.unshift({ requestFn, resolve, reject, retries: retries + 1 });
        processQueue(); // Attempt to process again after backoff
      }, backoffTime);
      
      return; 
    } else {
      if (isRateLimitError(error)) {
        console.error("Max retries reached for rate-limited request.");
        reject(new Error("Sonia is currently very popular! Please try again in a minute."));
      } else {
        // Try to extract a more meaningful error message from the response
        let errorMessage = "An unknown API error occurred.";
        try {
            let errorDetails = error;
             if (typeof errorDetails === 'string') {
                errorDetails = JSON.parse(errorDetails);
            }
            errorMessage = errorDetails?.error?.message || error.message || String(error);
        } catch {
            errorMessage = error.message || String(error);
        }
        reject(new Error(errorMessage));
      }
      // Stop processing on final failure
      isProcessing = false;
      processQueue(); // Attempt to process the next item in the queue
    }
  }
};

/**
 * Enqueues a function that returns a Promise (like an API call).
 * Ensures that only one such function executes at a time.
 * @param requestFn The function to execute.
 * @returns A Promise that resolves or rejects when the enqueued function completes.
 */
export const enqueueApiCall = <T>(requestFn: () => Promise<T>): Promise<T> => {
  return new Promise<T>((resolve, reject) => {
    queue.push({ requestFn, resolve, reject, retries: 0 });
    if (!isProcessing) {
      processQueue();
    }
  });
};