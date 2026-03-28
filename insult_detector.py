class InsultDetector:
    def __init__(self, insults):
        self.insults = insults

    def detect_insult(self, text):
        return any(insult in text for insult in self.insults)

# Demo usage
if __name__ == '__main__':
    with open('insult_library.json') as f:
        insults = json.load(f)['insults']
    detector = InsultDetector(insults)
    print(detector.detect_insult("You're as sharp as a marble!"))  # False
