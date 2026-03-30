"""
Mock travel data — hotels, activities, flights, weather.
──────────────────────────────────────────────────────────
No real APIs needed.  The Strands agent calls search_hotels / search_activities
tools which return data from these dicts, optionally filtered by type/budget.
"""

MOCK_HOTELS = {
    "Tokyo": [
        {"name": "Hotel Sunroute Ginza", "type": "boutique", "price": 135, "rating": 4.5, "neighborhood": "Ginza", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Shinjuku Granbell Hotel", "type": "boutique", "price": 120, "rating": 4.2, "neighborhood": "Shinjuku", "noise_level": "moderate", "veg_friendly": True},
        {"name": "APA Hotel Asakusa", "type": "chain", "price": 80, "rating": 3.8, "neighborhood": "Asakusa", "noise_level": "quiet", "veg_friendly": False},
        {"name": "Park Hyatt Tokyo", "type": "luxury", "price": 450, "rating": 4.9, "neighborhood": "Shinjuku", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Khaosan Tokyo Kabuki", "type": "hostel", "price": 30, "rating": 4.0, "neighborhood": "Asakusa", "noise_level": "noisy", "veg_friendly": False},
        {"name": "Nui. Hostel & Bar Lounge", "type": "hostel", "price": 35, "rating": 4.1, "neighborhood": "Kuramae", "noise_level": "moderate", "veg_friendly": True},
    ],
    "Barcelona": [
        {"name": "Hotel Neri", "type": "boutique", "price": 145, "rating": 4.6, "neighborhood": "Gothic Quarter", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Casa Bonay", "type": "boutique", "price": 135, "rating": 4.4, "neighborhood": "Eixample", "noise_level": "moderate", "veg_friendly": True},
        {"name": "W Barcelona", "type": "luxury", "price": 380, "rating": 4.7, "neighborhood": "Barceloneta", "noise_level": "moderate", "veg_friendly": True},
        {"name": "Generator Barcelona", "type": "hostel", "price": 28, "rating": 3.9, "neighborhood": "Gracia", "noise_level": "noisy", "veg_friendly": False},
        {"name": "Hilton Diagonal Mar", "type": "chain", "price": 160, "rating": 4.0, "neighborhood": "Diagonal Mar", "noise_level": "quiet", "veg_friendly": True},
    ],
    "Lisbon": [
        {"name": "Santiago de Alfama", "type": "boutique", "price": 130, "rating": 4.7, "neighborhood": "Alfama", "noise_level": "quiet", "veg_friendly": True},
        {"name": "The Lumiares", "type": "boutique", "price": 155, "rating": 4.5, "neighborhood": "Bairro Alto", "noise_level": "moderate", "veg_friendly": True},
        {"name": "Ibis Lisboa Centro", "type": "chain", "price": 65, "rating": 3.5, "neighborhood": "Baixa", "noise_level": "moderate", "veg_friendly": False},
        {"name": "Four Seasons Ritz", "type": "luxury", "price": 520, "rating": 4.9, "neighborhood": "Avenida da Liberdade", "noise_level": "quiet", "veg_friendly": True},
    ],
    "Osaka": [
        {"name": "Hotel Intergate Osaka", "type": "boutique", "price": 110, "rating": 4.3, "neighborhood": "Umeda", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Cross Hotel Osaka", "type": "boutique", "price": 125, "rating": 4.4, "neighborhood": "Shinsaibashi", "noise_level": "moderate", "veg_friendly": True},
        {"name": "Ritz-Carlton Osaka", "type": "luxury", "price": 400, "rating": 4.8, "neighborhood": "Umeda", "noise_level": "quiet", "veg_friendly": True},
        {"name": "First Cabin Midousuji-Namba", "type": "hostel", "price": 40, "rating": 3.7, "neighborhood": "Namba", "noise_level": "noisy", "veg_friendly": False},
    ],
    "Paris": [
        {"name": "Hôtel Grand Amour", "type": "boutique", "price": 150, "rating": 4.5, "neighborhood": "10th arrondissement", "noise_level": "moderate", "veg_friendly": True},
        {"name": "Le Marais boutique", "type": "boutique", "price": 140, "rating": 4.4, "neighborhood": "Le Marais", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Ibis Styles Gare du Nord", "type": "chain", "price": 90, "rating": 3.6, "neighborhood": "Gare du Nord", "noise_level": "noisy", "veg_friendly": False},
        {"name": "Shangri-La Paris", "type": "luxury", "price": 600, "rating": 4.9, "neighborhood": "16th arrondissement", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Generator Paris", "type": "hostel", "price": 32, "rating": 3.8, "neighborhood": "10th arrondissement", "noise_level": "noisy", "veg_friendly": False},
    ],
    "Rome": [
        {"name": "Hotel Raphael", "type": "boutique", "price": 155, "rating": 4.6, "neighborhood": "Piazza Navona", "noise_level": "quiet", "veg_friendly": True},
        {"name": "Chapter Roma", "type": "boutique", "price": 140, "rating": 4.3, "neighborhood": "Trastevere", "noise_level": "moderate", "veg_friendly": True},
        {"name": "NH Collection Roma Centro", "type": "chain", "price": 120, "rating": 4.0, "neighborhood": "Centro", "noise_level": "moderate", "veg_friendly": True},
        {"name": "The Yellow Hostel", "type": "hostel", "price": 25, "rating": 4.2, "neighborhood": "Termini", "noise_level": "noisy", "veg_friendly": False},
    ],
    "Bangkok": [
        {"name": "Riva Surya Bangkok", "type": "boutique", "price": 95, "rating": 4.4, "neighborhood": "Phra Nakhon", "noise_level": "quiet", "veg_friendly": True},
        {"name": "The Siam", "type": "luxury", "price": 350, "rating": 4.8, "neighborhood": "Dusit", "noise_level": "quiet", "veg_friendly": True},
        {"name": "NapPark Hostel", "type": "hostel", "price": 15, "rating": 4.3, "neighborhood": "Khao San", "noise_level": "noisy", "veg_friendly": True},
        {"name": "Ibis Bangkok Riverside", "type": "chain", "price": 55, "rating": 3.7, "neighborhood": "Riverside", "noise_level": "moderate", "veg_friendly": False},
    ],
    "New York": [
        {"name": "The Marlton", "type": "boutique", "price": 160, "rating": 4.5, "neighborhood": "Greenwich Village", "noise_level": "moderate", "veg_friendly": True},
        {"name": "citizenM Times Square", "type": "boutique", "price": 140, "rating": 4.3, "neighborhood": "Midtown", "noise_level": "noisy", "veg_friendly": True},
        {"name": "Pod 51", "type": "hostel", "price": 75, "rating": 3.9, "neighborhood": "Midtown East", "noise_level": "moderate", "veg_friendly": False},
        {"name": "The Plaza", "type": "luxury", "price": 700, "rating": 4.9, "neighborhood": "Central Park South", "noise_level": "quiet", "veg_friendly": True},
    ],
}

MOCK_ACTIVITIES = {
    "Tokyo": [
        {"name": "Tsukiji Outer Market Food Tour", "type": "food", "duration": "3hr", "price": 45, "crowd_level": "moderate"},
        {"name": "Meiji Shrine & Harajuku Walk", "type": "cultural", "duration": "2hr", "price": 0, "crowd_level": "low"},
        {"name": "Shibuya Crossing & Hachiko Photo Spot", "type": "sightseeing", "duration": "1hr", "price": 0, "crowd_level": "very_high"},
        {"name": "Akihabara Electronics District", "type": "shopping", "duration": "3hr", "price": 0, "crowd_level": "high"},
        {"name": "TeamLab Borderless Digital Art", "type": "cultural", "duration": "2hr", "price": 30, "crowd_level": "high"},
        {"name": "Yanaka Old Town Walking Tour", "type": "cultural", "duration": "2.5hr", "price": 20, "crowd_level": "low"},
        {"name": "Ramen Tasting in Shinjuku", "type": "food", "duration": "2hr", "price": 25, "crowd_level": "moderate"},
        {"name": "Asakusa Temple & Senso-ji", "type": "cultural", "duration": "1.5hr", "price": 0, "crowd_level": "high"},
        {"name": "Mt. Takao Day Hike", "type": "adventure", "duration": "5hr", "price": 10, "crowd_level": "moderate"},
    ],
    "Barcelona": [
        {"name": "Gothic Quarter Walking Tour", "type": "cultural", "duration": "2.5hr", "price": 15, "crowd_level": "moderate"},
        {"name": "La Boqueria Market Food Tour", "type": "food", "duration": "3hr", "price": 50, "crowd_level": "high"},
        {"name": "Sagrada Familia Visit", "type": "sightseeing", "duration": "2hr", "price": 26, "crowd_level": "very_high"},
        {"name": "El Born Tapas & Wine Walk", "type": "food", "duration": "3hr", "price": 60, "crowd_level": "moderate"},
        {"name": "Montjuïc Castle & Gardens", "type": "cultural", "duration": "3hr", "price": 10, "crowd_level": "low"},
        {"name": "Barceloneta Beach & Seafood", "type": "relaxation", "duration": "4hr", "price": 0, "crowd_level": "high"},
        {"name": "Gràcia Neighborhood Art Walk", "type": "cultural", "duration": "2hr", "price": 0, "crowd_level": "low"},
        {"name": "Day Trip to Montserrat", "type": "adventure", "duration": "6hr", "price": 35, "crowd_level": "moderate"},
    ],
    "Lisbon": [
        {"name": "Alfama Fado & Street Food Tour", "type": "food", "duration": "3hr", "price": 40, "crowd_level": "moderate"},
        {"name": "Belém Tower & Pastéis de Belém", "type": "cultural", "duration": "2hr", "price": 10, "crowd_level": "high"},
        {"name": "Tram 28 Scenic Ride", "type": "sightseeing", "duration": "1hr", "price": 3, "crowd_level": "very_high"},
        {"name": "Baixa & Chiado Walking Tour", "type": "cultural", "duration": "2.5hr", "price": 0, "crowd_level": "moderate"},
        {"name": "Time Out Market Food Hall", "type": "food", "duration": "2hr", "price": 30, "crowd_level": "high"},
        {"name": "Day Trip to Sintra Palaces", "type": "cultural", "duration": "6hr", "price": 25, "crowd_level": "high"},
        {"name": "LX Factory Art & Brunch", "type": "food", "duration": "2hr", "price": 20, "crowd_level": "low"},
    ],
    "Osaka": [
        {"name": "Dotonbori Street Food Walk", "type": "food", "duration": "3hr", "price": 30, "crowd_level": "high"},
        {"name": "Osaka Castle History Tour", "type": "cultural", "duration": "2hr", "price": 8, "crowd_level": "moderate"},
        {"name": "Kuromon Market Brunch", "type": "food", "duration": "2hr", "price": 25, "crowd_level": "moderate"},
        {"name": "Shinsekai Retro District Walk", "type": "cultural", "duration": "2hr", "price": 0, "crowd_level": "moderate"},
        {"name": "Day Trip to Nara Deer Park", "type": "adventure", "duration": "5hr", "price": 15, "crowd_level": "moderate"},
        {"name": "Osaka Aquarium Kaiyukan", "type": "sightseeing", "duration": "3hr", "price": 20, "crowd_level": "high"},
    ],
    "Paris": [
        {"name": "Montmartre Art & Crêpe Tour", "type": "food", "duration": "3hr", "price": 45, "crowd_level": "moderate"},
        {"name": "Louvre Museum Highlights", "type": "cultural", "duration": "3hr", "price": 17, "crowd_level": "very_high"},
        {"name": "Le Marais Food & History Walk", "type": "food", "duration": "3hr", "price": 55, "crowd_level": "moderate"},
        {"name": "Seine River Sunset Cruise", "type": "relaxation", "duration": "1.5hr", "price": 15, "crowd_level": "moderate"},
        {"name": "Eiffel Tower Visit", "type": "sightseeing", "duration": "2hr", "price": 26, "crowd_level": "very_high"},
        {"name": "Hidden Passages Walking Tour", "type": "cultural", "duration": "2.5hr", "price": 10, "crowd_level": "low"},
        {"name": "Versailles Day Trip", "type": "cultural", "duration": "6hr", "price": 20, "crowd_level": "high"},
    ],
    "Rome": [
        {"name": "Trastevere Street Food Tour", "type": "food", "duration": "3hr", "price": 50, "crowd_level": "moderate"},
        {"name": "Colosseum & Roman Forum", "type": "cultural", "duration": "3hr", "price": 16, "crowd_level": "very_high"},
        {"name": "Vatican Museums & Sistine Chapel", "type": "cultural", "duration": "4hr", "price": 20, "crowd_level": "very_high"},
        {"name": "Testaccio Market & Pasta Making", "type": "food", "duration": "3hr", "price": 60, "crowd_level": "low"},
        {"name": "Appian Way Bike Ride", "type": "adventure", "duration": "3hr", "price": 30, "crowd_level": "low"},
        {"name": "Jewish Ghetto Walking Tour", "type": "cultural", "duration": "2hr", "price": 10, "crowd_level": "low"},
    ],
    "Bangkok": [
        {"name": "Chinatown Street Food Tour", "type": "food", "duration": "3hr", "price": 25, "crowd_level": "high"},
        {"name": "Grand Palace & Wat Pho", "type": "cultural", "duration": "3hr", "price": 15, "crowd_level": "very_high"},
        {"name": "Floating Market Day Trip", "type": "cultural", "duration": "5hr", "price": 30, "crowd_level": "high"},
        {"name": "Thai Cooking Class", "type": "food", "duration": "4hr", "price": 35, "crowd_level": "low"},
        {"name": "Khao San Road Night Walk", "type": "sightseeing", "duration": "2hr", "price": 0, "crowd_level": "very_high"},
        {"name": "Jim Thompson House & Garden", "type": "cultural", "duration": "1.5hr", "price": 8, "crowd_level": "low"},
    ],
    "New York": [
        {"name": "Greenwich Village Food Tour", "type": "food", "duration": "3hr", "price": 55, "crowd_level": "moderate"},
        {"name": "Central Park Walking Tour", "type": "cultural", "duration": "2hr", "price": 0, "crowd_level": "moderate"},
        {"name": "Times Square Experience", "type": "sightseeing", "duration": "1hr", "price": 0, "crowd_level": "very_high"},
        {"name": "Brooklyn Bridge & DUMBO Walk", "type": "cultural", "duration": "2hr", "price": 0, "crowd_level": "high"},
        {"name": "Chelsea Market & High Line", "type": "food", "duration": "3hr", "price": 30, "crowd_level": "high"},
        {"name": "Harlem Jazz & Soul Food Night", "type": "food", "duration": "3hr", "price": 45, "crowd_level": "low"},
    ],
}

MOCK_FLIGHTS = {
    "Tokyo":     {"airline": "ANA", "price": 850, "duration": "14hr"},
    "Barcelona": {"airline": "Iberia", "price": 520, "duration": "8hr"},
    "Lisbon":    {"airline": "TAP Portugal", "price": 480, "duration": "7.5hr"},
    "Osaka":     {"airline": "JAL", "price": 880, "duration": "14.5hr"},
    "Paris":     {"airline": "Air France", "price": 550, "duration": "7hr"},
    "Rome":      {"airline": "Alitalia", "price": 510, "duration": "9hr"},
    "Bangkok":   {"airline": "Thai Airways", "price": 720, "duration": "17hr"},
    "New York":  {"airline": "Delta", "price": 320, "duration": "2.5hr"},
}

MOCK_WEATHER = {
    "Tokyo":     {"Jan": "Cold, 5°C", "Feb": "Cold, 7°C", "Mar": "Mild, 12°C", "Apr": "Pleasant, 17°C", "May": "Warm, 22°C", "Jun": "Rainy, 24°C", "Jul": "Hot & humid, 29°C", "Aug": "Hot & humid, 30°C", "Sep": "Warm, 26°C", "Oct": "Pleasant, 20°C", "Nov": "Mild, 14°C", "Dec": "Cold, 8°C"},
    "Barcelona": {"Jan": "Mild, 11°C", "Feb": "Mild, 12°C", "Mar": "Mild, 14°C", "Apr": "Pleasant, 17°C", "May": "Warm, 21°C", "Jun": "Hot, 25°C", "Jul": "Hot, 28°C", "Aug": "Hot & crowded, 28°C", "Sep": "Warm, 25°C", "Oct": "Pleasant, 20°C", "Nov": "Mild, 15°C", "Dec": "Mild, 12°C"},
    "Lisbon":    {"Jan": "Mild, 12°C", "Feb": "Mild, 13°C", "Mar": "Pleasant, 16°C", "Apr": "Pleasant, 18°C", "May": "Warm, 21°C", "Jun": "Hot, 25°C", "Jul": "Hot, 28°C", "Aug": "Hot, 28°C", "Sep": "Warm, 25°C", "Oct": "Pleasant, 20°C", "Nov": "Mild, 16°C", "Dec": "Mild, 13°C"},
    "Osaka":     {"Jan": "Cold, 6°C", "Feb": "Cold, 7°C", "Mar": "Mild, 11°C", "Apr": "Pleasant, 17°C", "May": "Warm, 22°C", "Jun": "Rainy, 25°C", "Jul": "Hot & humid, 30°C", "Aug": "Hot & humid, 31°C", "Sep": "Warm, 27°C", "Oct": "Pleasant, 20°C", "Nov": "Mild, 14°C", "Dec": "Cold, 8°C"},
    "Paris":     {"Jan": "Cold, 5°C", "Feb": "Cold, 6°C", "Mar": "Mild, 10°C", "Apr": "Pleasant, 14°C", "May": "Warm, 18°C", "Jun": "Warm, 21°C", "Jul": "Warm, 24°C", "Aug": "Warm, 24°C", "Sep": "Pleasant, 20°C", "Oct": "Mild, 14°C", "Nov": "Cold, 9°C", "Dec": "Cold, 6°C"},
    "Rome":      {"Jan": "Mild, 9°C", "Feb": "Mild, 10°C", "Mar": "Mild, 13°C", "Apr": "Pleasant, 16°C", "May": "Warm, 21°C", "Jun": "Hot, 26°C", "Jul": "Hot, 29°C", "Aug": "Hot & crowded, 29°C", "Sep": "Warm, 25°C", "Oct": "Pleasant, 19°C", "Nov": "Mild, 13°C", "Dec": "Mild, 10°C"},
    "Bangkok":   {"Jan": "Hot, 32°C", "Feb": "Hot, 33°C", "Mar": "Very hot, 34°C", "Apr": "Very hot, 35°C", "May": "Hot & rainy, 34°C", "Jun": "Rainy, 33°C", "Jul": "Rainy, 32°C", "Aug": "Rainy, 32°C", "Sep": "Rainy, 31°C", "Oct": "Rainy, 31°C", "Nov": "Pleasant, 31°C", "Dec": "Pleasant, 31°C"},
    "New York":  {"Jan": "Cold, 1°C", "Feb": "Cold, 3°C", "Mar": "Mild, 8°C", "Apr": "Pleasant, 15°C", "May": "Warm, 20°C", "Jun": "Hot, 26°C", "Jul": "Hot & humid, 29°C", "Aug": "Hot & humid, 28°C", "Sep": "Warm, 24°C", "Oct": "Pleasant, 17°C", "Nov": "Cool, 11°C", "Dec": "Cold, 4°C"},
}

# Country mapping for search
DESTINATION_COUNTRY = {
    "Tokyo": "Japan",
    "Osaka": "Japan",
    "Barcelona": "Spain",
    "Lisbon": "Portugal",
    "Paris": "France",
    "Rome": "Italy",
    "Bangkok": "Thailand",
    "New York": "United States",
}

