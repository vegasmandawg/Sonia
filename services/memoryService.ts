import type { UserMemory } from '../types';

const MEMORY_KEY = 'sonia_memory';

/**
 * Loads the user's memory object from localStorage.
 */
export const loadMemory = (): UserMemory => {
    try {
        const memoryJson = localStorage.getItem(MEMORY_KEY);
        return memoryJson ? JSON.parse(memoryJson) : {};
    } catch (error: any) {
        console.error("Failed to load memory from localStorage:", error);
        return {};
    }
};

/**
 * Saves the entire memory object to localStorage. Used for direct manipulation.
 * @param memory The complete UserMemory object to save.
 */
export const saveFullMemory = (memory: UserMemory) => {
    try {
        localStorage.setItem(MEMORY_KEY, JSON.stringify(memory));
    } catch (error: any) {
        console.error("Failed to save full memory to localStorage:", error);
    }
};


/**
 * Merges new details into the existing memory and saves to localStorage.
 * It intelligently combines array values and updates timestamps for all new info.
 * @param newDetails The new memory details to add, as a plain object.
 */
export const mergeAndSaveMemory = (newDetails: { [key: string]: any }) => {
    try {
        const memory = loadMemory();

        for (const key in newDetails) {
            const newValue = newDetails[key];

            // Skip invalid new values
            if (newValue === undefined || newValue === null || String(newValue).trim() === '' || (Array.isArray(newValue) && newValue.length === 0)) {
                continue;
            }

            const oldValueItem = memory[key];

            if (Array.isArray(newValue)) {
                const oldArray = (oldValueItem && Array.isArray(oldValueItem.value)) ? oldValueItem.value : [];
                // Merge and remove duplicates from arrays
                const combinedValue = [...new Set([...oldArray, ...newValue])];
                memory[key] = { value: combinedValue, timestamp: Date.now() };
            } else {
                // Overwrite/create non-array values
                memory[key] = { value: newValue, timestamp: Date.now() };
            }
        }
        
        saveFullMemory(memory);

    } catch (error: any) {
        console.error("Failed to save memory to localStorage:", error);
    }
};