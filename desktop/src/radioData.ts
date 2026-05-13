export type Track = {
  id?: string;
  candidateId?: string;
  title: string;
  artist: string;
  duration: number;
  playbackUrl?: string;
  source?: string;
};

export type Station = {
  id: string;
  title: string;
  subtitle: string;
  city: string;
  condition: string;
  temperature: number;
  weather: string;
  agentLine: string;
  greeting?: string;
  chatReply?: string;
  sessionId?: string;
  ttsAudioUrl?: string;
  tracks: Track[];
};

export type ChatMessage = {
  id: string;
  role: "agent" | "user";
  text: string;
  time: string;
};

export const emptyStation: Station = {
  id: "initializing",
  title: "Tuning Signal",
  subtitle: "Initializing",
  city: "Guangzhou",
  condition: "...",
  temperature: 27,
  weather: "...",
  agentLine: "",
  tracks: [
    {
      id: "initializing-track",
      title: "...",
      artist: "...",
      duration: 180,
    },
  ],
};

export const stations: Station[] = [
  {
    id: "jam",
    title: "Jam Radio",
    subtitle: "The Wavelength",
    city: "Shanghai",
    condition: "Clear",
    temperature: 26,
    weather: "Sunny",
    agentLine: "Good morning. I tuned the station for a bright, creative day.",
    tracks: [
      { title: "Changing the Theater Beat", artist: "The Daily", duration: 216 },
      { title: "Sunlit Errands", artist: "Mina Park", duration: 188 },
      { title: "Balcony Walk", artist: "Northline", duration: 204 },
    ],
  },
  {
    id: "city",
    title: "City Live",
    subtitle: "Urban Flow",
    city: "Shanghai",
    condition: "Clear",
    temperature: 26,
    weather: "Sunny",
    agentLine: "I brought the tempo forward without making the room feel crowded.",
    tracks: [
      { title: "Metro Signal", artist: "Glass Avenue", duration: 192 },
      { title: "Late Tram Bloom", artist: "Juno Vale", duration: 210 },
      { title: "Soft Engine", artist: "Harbor Steps", duration: 176 },
    ],
  },
  {
    id: "lofi",
    title: "Lofi Lounge",
    subtitle: "Chillhop Beats",
    city: "Shanghai",
    condition: "Clear",
    temperature: 26,
    weather: "Sunny",
    agentLine: "I softened the edges and kept the pulse low, like a lamp left on.",
    tracks: [
      { title: "Paper Lantern", artist: "Blue Room Tape", duration: 224 },
      { title: "Quiet Keys", artist: "Nara Fields", duration: 206 },
      { title: "Afterglow Sketch", artist: "Rue Indigo", duration: 198 },
    ],
  },
];
