import React, { useState, useEffect } from 'react';

interface AgeGateProps {
  onConfirm: () => void;
}

const AgeGate: React.FC<AgeGateProps> = ({ onConfirm }) => {
  const [dob, setDob] = useState('');
  const [ageConfirmed, setAgeConfirmed] = useState(false);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [isButtonEnabled, setIsButtonEnabled] = useState(false);

  const calculateAge = (dateString: string) => {
    const today = new Date();
    const birthDate = new Date(dateString);
    let age = today.getFullYear() - birthDate.getFullYear();
    const m = today.getMonth() - birthDate.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    return age;
  };

  useEffect(() => {
    const age = calculateAge(dob);
    setAgeConfirmed(age >= 18);
  }, [dob]);

  useEffect(() => {
    setIsButtonEnabled(ageConfirmed && termsAccepted);
  }, [ageConfirmed, termsAccepted]);
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-800 rounded-2xl p-8 max-w-md w-full shadow-2xl shadow-fuchsia-500/10 border border-white/10">
        <h2 className="text-2xl font-bold text-center text-violet-300 mb-4">Age Verification</h2>
        <p className="text-gray-400 text-center mb-6">You must be 18 years or older to use this application.</p>
        
        <div className="mb-4">
          <label htmlFor="dob" className="block text-sm font-medium text-gray-300 mb-2">Date of Birth</label>
          <input
            type="date"
            id="dob"
            value={dob}
            onChange={(e) => setDob(e.target.value)}
            className="w-full bg-gray-700 border border-gray-600 rounded-lg p-2.5 text-white focus:ring-fuchsia-500 focus:border-fuchsia-500"
            max={new Date().toISOString().split("T")[0]} // User cannot select future date
          />
        </div>
        
        {dob && !ageConfirmed && (
            <p className="text-red-400 text-sm text-center mb-4">You must be at least 18 years old to proceed.</p>
        )}

        <div className="space-y-4 mb-8">
            <label className="flex items-start space-x-3 cursor-pointer">
                <input
                    type="checkbox"
                    checked={termsAccepted}
                    onChange={() => setTermsAccepted(!termsAccepted)}
                    className="mt-1 h-5 w-5 rounded bg-gray-700 border-gray-500 text-fuchsia-500 focus:ring-fuchsia-500"
                />
                <span className="text-gray-400 text-sm">
                    I have read and agree to the <a href="#" className="text-violet-400 hover:underline">Terms of Service</a> and <a href="#" className="text-violet-400 hover:underline">Privacy Policy</a>. I understand this application contains mature themes and user-generated explicit content.
                </span>
            </label>
        </div>

        <button
          onClick={onConfirm}
          disabled={!isButtonEnabled}
          className="w-full bg-fuchsia-500 text-white font-bold py-3 rounded-lg transition-all duration-300 disabled:bg-gray-600 disabled:cursor-not-allowed hover:enabled:bg-fuchsia-600 focus:outline-none focus:ring-4 focus:ring-fuchsia-500/50"
        >
          Proceed
        </button>
      </div>
    </div>
  );
};

export default AgeGate;