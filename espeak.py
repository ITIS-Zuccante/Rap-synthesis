import sys;
import os;
import subprocess;
import time;
import wave;
import struct;
import math;
import argparse;


#Suppress prints (not recommended), mainly for quick execution
#sys.stdout = open(os.devnull, 'w');

"""
eSpeak creates wavs with the following parameters: (ofc nframes varies)
(nchannels=1, sampwidth=2, framerate=22050, nframes=1073739776, 
	comptype='NONE', compname='not compressed')

MBROLA KÄYTTÄÄ framerate=16000!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!


https://www.youtube2mp3.cc
http://www.online-convert.com/
MONO! framerate 22050! PCM = default!


DONE:

Korjaa foneemihommat								DONE
Lyriikoihin riimiosaan ennen vokaalia painotukset 	DONE ->tweak
-> rimmaava osa päättyy aina samaan aikaan			DONE
tuplaus riimiosassa?								DONE ->tweak
Korjaa ajotus(jotkut wavit ylittää tahtirajan)		DONE 
->Kokeile trimmaa kaikki wavit ennen parseemista	DONE ->tweak
wpm vakio? laske pisimmän lainin mukaan				DONE 
->Laske keskiarvo wpm, jos rivin wpm abs ku 		DONE ->tweak
  WPMTHRESHOLD, luo joko taukoa tai syntetisoi 
  alkuperäsellä wpmllä, muuten keskiarvolla.
TRIM: Lisää vähän taukoo riimiosan loppuun, alkaa	DONE 
  liian yhtäkkisesti seuraava rivi
Muokkaa doublen ääntä järkevämmäksi (eri m?)		DONE
mbrola äänet  										DONE
Jos wpm liian pieni -> luo mielummin taukoa alkuun  DONE (ei hyvä, on flagi)
Jos ylipitkä tahti, tallenna erotus ja nipistä		DONE (EI TESTATTU)
	seuraavasta hiljaisuudesta pois että rytmi OK   



TODO:

jos wpm liian iso, jaa rivi kahtia? toimisko? 		EHKÄ MYÖHEMMIN
kokeile beatboxin kaa 								EHKÄ MYÖHEMMIN

TESTAA PARAMETREJA!!!!!!!!!!!!!!





"""

def initialize(options):
	global WPMTHRESHOLD, WPMTOOSMALL, WPMTOOHIGH, WPMBOOST, DOUBLEDELAY;
	global DBCHUNKSIZE, USEMBROLAVOICE, DEFAULTAMPLITUDE, DEFAULTPITCH;
	global DEFAULTRHYMEAMPLITUDE, DEFAULTRHYMEPITCH, DEFAULTDOUBLEAMPLITUDE;
	global DEFAULTDOUBLEPITCH, DEFAULTLANGVOICE, DOUBLELANGVOICE;
	global NCHANNELS, SAMPLEWIDTH, FRAMERATE;
	global LYRICDIR, SONGDIR, BEATDIR;

	LYRICDIR = "lyrics/";	#espeak can't be given a save directory so all wavs
							#are slammed into the working directory. Instead,
							#lyricfiles are separated (and wavs removed after
							#synthesis)
	SONGDIR = "songs/";		#Output directory
	BEATDIR = "beats/";		#Accompanying beats dir

	#EXPERIMENT WITH THESE
	WPMTHRESHOLD = 40;	#Use this to implement whether to add pause... 
	WPMTOOSMALL = 90;	#If WPM would be under this threshold, add pause NOTDONE
	WPMTOOHIGH = 200; #MAYBE TWICE THE BPM
	WPMBOOST = -55;		#some songs require increased wpm to stay in beat
						#TRIM FIXES THIS, but the effect is very pronounced
						#NOW it is used to stretch the rhymes as much as possib
						#	trying to minimize the silence
	#This is getting crazy, boost can vary from 0 to -80!!!! between songs,
	#something wrong

	DOUBLEDELAY = 0.015;#The delay for double tracking, EXPERIMENT 10-20ms
	DBCHUNKSIZE = 50;	#The size of one chunk when calculating db (and trim)


	
	USEMBROLAVOICE = options['mbrola'];	#If true, uses mbrola instead of espeak

	#Arguments for espeak synthesis. Takes everything as a string so string here
	#WARNING, THE EFFECT OF THESE DIFFERS WHEN USING MBROLA.
	#NOW SET TO OPTIMIZE MBROLA
	DEFAULTAMPLITUDE = "130";		#Default amplitude(volume) for synthesis
	DEFAULTPITCH = "65";#70			#The pitch for everything else except rhyme
	DEFAULTRHYMEAMPLITUDE = "220";  #Amplitude (Volume) of rhyming part
	DEFAULTRHYMEPITCH = "70";#15	#Lowered pitch for the rhyming part
	DEFAULTDOUBLEAMPLITUDE = "190"; #Amplitude for double track
	DEFAULTDOUBLEPITCH = "60";		#Pitch for double track

	if(USEMBROLAVOICE):
		DEFAULTLANGVOICE = " mb-en1"; 	#MBROLA VOICE
		DOUBLELANGVOICE = " mb-us2";	#DOUBLE MBROLA VOICE
	else:
		DEFAULTLANGVOICE = "en+m3"; 	#This would seem to sound the most nat
		DOUBLELANGVOICE = "en+m1";	#Is used as the double if doubling enabled


	#DON'T CHANGE THESE, Default parameters for espeak wavs
	NCHANNELS = 1;
	SAMPLEWIDTH = 2;
	if(USEMBROLAVOICE):
		FRAMERATE = 16000.0;	#Framerate used by mbrola in wavs
	else:
		FRAMERATE = 22050.0;	#Framerate used by espeak in wavs

############################## SHELL STUFF AND COMMANDS #######################

#Execute shell commands
def execute(input):		
	p = subprocess.Popen(input, stdout=subprocess.PIPE, 
		stderr=subprocess.PIPE, stdin=subprocess.PIPE, shell=True); 
	(output, err) = p.communicate();
	if err:
		print(str(err));
	return output;

#Use unix's aplay to play wavs PRODUCES A DELAY OF APPROX. 150 ms
def play(filename):		
	return execute("aplay -q %s.wav" % filename);	#-q = quiet

#Simplify espeak command a bit
def speak(language, flags, input):	
	#print("Speaking: \n%s" % input);
	return execute("espeak -v%s %s \"%s\"" % (language,flags,input));

#Save espeak output as wav -v mb-en1
def save_wav(language,flags,input,filename):	
	#STDOUT>wav PRODUCES WRONG DURATION FROM FRAMES
	return execute("espeak -v%s %s -w %s.wav \"%s\""%
		(language,flags,filename,input));

#DELETES all temporary files associated with song_name: Individual lines, 
#created doubles, silences etc. Leaves the finished synthesized lyrics intact.
#Move is exclusive, either move or remove
def clean_directory(song_name, move, inquire=False):	
	if (move):	
		execute("mv "+str(song_name)+".wav "+SONGDIR); #Allow choice here
	else:
		#if (input("About the remove individual wav-files. Results are safe."
			#+"Continue? [y/n]") is not "y" or inquire):
			#print("CLEANING ABORTED.");
			#return 1;
		execute("rm " + song_name+"-*");
		execute("rm silence*");
		print("Directory cleaned.");

#Lists lyricfiles, wave files and beat files according to parameters
#REMOVES W FROM LOW WHEN LISTING BEATS WHYYYYYY
def list_files(directory, grep):
	if (directory is BEATDIR):
		print("Detecting flag mbrola = " + str(USEMBROLAVOICE));
		if (USEMBROLAVOICE): print("Choose <xxxlow>");
		else: print("Choose <xxxhigh>");

	print("+----------");
	s = str(execute("ls -p "+directory+" | grep -v '/$' | grep "+grep), 
		encoding='UTF-8');
	#print(s);
	#s = str(s, encoding='UTF-8');
	for line in s.splitlines():
		print("| "+line.strip(".wav"));	#WHY DOES THIS REMOVE ONE W FROM LOW???
	print("+----------");

######################## WAVE MANIPULATION AND SYNTHESIS ######################

#NOW EXPECTS BPM AS THE FIRST LINE! (implement flags also?)
#Opens the lyric file to extract bpm, line wordcount and lyrics.
#Return rhymelist with the line wordcount, first part and rhyming part
def read_file2(filename):	
	print("----/ READING: %s \\-----" % filename);
	rhymelist = [];

	try:
		rhymefile = open(LYRICDIR+filename,"r");
	except (IOError):
		print("ERROR OPENING FILE " + filename);
		return 0;
	print(rhymefile);
	
	try:
		BPM = int(rhymefile.readline().strip());
	except ValueError:
		print("ERROR, EXPECTING BPM AS THE FIRST LINE");
		print("RECEIVED: " + str(BPM));
		return 0;
	
	print("EXTRACTED BPM = " + str(BPM));
	rhymelist.append(BPM);
	for line in rhymefile:
		#print(line);
		rhyme = line.split("_");
		print("Rhyme = ");
		print(rhyme);
		if (len(rhyme)==1 or not rhyme):	#To allow empty lines
			print("EMPTY LINE");
			words = 0;
			rhyme=["",""];
		else:
			words = len(rhyme[0].split())+len(rhyme[1].split());
		rhymelist.append((words,rhyme)); # nOfWords, rhymes[] (1,2)
	print("----/ LYRICS: \\------");
	for i in range(1,len(rhymelist)):
		print(rhymelist[i][0]);		#line wordcount
		print(rhymelist[i][1][0]);	#first part of line
		print(rhymelist[i][1][1]); 	#rhyming part

	return rhymelist;


def synthesize_raw(song_name, clean=True):
	rhymelist=read_file2(song_name);
	n_of_wavs = len(rhymelist);
	words="";

	for i in range(1,n_of_wavs):
		words+=rhymelist[i][1][0]+" "+rhymelist[i][1][1];

	save_wav(" en", "",words,song_name+"FINAL");

	#compiled_song = combine_wavs(song_array, song_name,True);
	time_wav(song_name+"FINAL");
	#if (clean):
	#	clean_directory(compiled_song,False); #Don't move the result
	return (song_name+"FINAL");


#Creates wav files based on the rhymelist from read_file2()
#Saves the first part and rhyming part separately as <name>-<line>-<0 or 1>
def synthesize_lines(song_name, rhymelist, language, flags, double=False, 
	constant_WPM=False):

	print("----/ SYNTHESIZING \\-----");
	
	bpm=rhymelist[0];
	wpm=0;
	mean_wpm=0;
	counter=0.0;
	line_status=0; #0=not calculated, 1=faster than wpm, 2=slower, 3=use mean
	wpm_list=[[0 for j in range(len(rhymelist))] for i in range(2)];
	
	if (constant_WPM):
		print("Constant wpm calculation...");
		for i in range(1,len(rhymelist)): #NOT TESTED
			if (rhymelist[i][0] is not 0):
				mean_wpm+=(WPMBOOST+round(bpm/4.0*(rhymelist[i][0])));
				print("mean = " + str(mean_wpm)+", counter="+str(counter));
				counter+=1.0;
		#THIS GETS MAX wpm=str(max(wpm,(0+round(bpm/4.0*(1+rhymelist[i][0])))));
		mean_wpm=int(round(mean_wpm/counter));
		#print("CALCULATED WPM MEAN = "+ str(mean_wpm));


	print("BPM="+str(bpm)+", mean_WPM="+str(mean_wpm)+", Threshold="
		+str(WPMTHRESHOLD)+", WPMTOOSMALL="+str(WPMTOOSMALL)+", WPMTOOHIGH="
		+str(WPMTOOHIGH));

	for i in range(1,len(rhymelist)):
		print(i);
		name = song_name + "-" + str(i);	
		nwords=rhymelist[i][0];
		#Bars per minute *words in line(bar) = words per minute
		if(rhymelist[i][0] is not 0):
			wpm = WPMBOOST+round(bpm/4.0*(nwords));
			#if (wpm>WPMTOOHIGH):	###
			#	wpm=WPMTOOHIGH;		###
			wpm_list[0][i-1]=wpm;
			if (constant_WPM):
				if (wpm>mean_wpm+WPMTHRESHOLD): #Way fast, use it and weep
					print("wpm over threshold, nothing we can do about it");
					if (wpm>=WPMTOOHIGH):	#SOMEHOW SPLIT TO TWO LINES?
						line_status=1;		#OR IMPLEMENT UPBEAT with penalty
						wpm=WPMTOOHIGH;	#IS THIS OK?????
						wpm_list[1][i-1]=wpm;
						wpm=str(wpm);
					else: #Sounds better slower
						wpm=str(round((WPMTOOHIGH+mean_wpm)/2.0));	 
						wpm_list[1][i-1]=round((WPMTOOHIGH+mean_wpm)/2.0);
					
				elif (wpm<mean_wpm-WPMTHRESHOLD): #Way too slow, add pause
					print("Slower than mean wmp, corrected to mean. difference:"
						 + str(mean_wpm-wpm));
					line_status=2;
					if(wpm<WPMTOOSMALL): #Lines with just few words

						wpm=str(round((WPMTOOSMALL+mean_wpm)/2.0));
						wpm_list[1][i-1]=round((WPMTOOSMALL+mean_wpm)/2.0);
						print("WPM TOO SMALL -> "+wpm);
						#pass; #Decide wether to use the mean or add pause
					else:
						wpm_list[1][i-1]=mean_wpm;	#SOMEHOW START_SILENCE HERE
						wpm=str(mean_wpm);
				else: #WPM falls within the bounds of threshold, use the mean
					print("Wpm within mean threshold. difference: " 
						+ str(mean_wpm-wpm));
					line_status=3;
					wpm_list[1][i-1]=mean_wpm;
					wpm=str(mean_wpm);
		else:
			wpm = "0"; 
			wpm_list[0][i-1]=wpm;
			wpm_list[1][i-1]=wpm;
		wpm=str(wpm);
		print("saving line \"%s\" as %s. WPM = %s" % 
			(rhymelist[i][1][0],(name + "-0.wav."),wpm));
		save_wav(language,(flags + (" -p "+DEFAULTPITCH+" -a "+DEFAULTAMPLITUDE) 
			+ (" -s "+wpm)),rhymelist[i][1][0], (name + "-0")); #FIRST PART
		print("saving line \"%s\" as %s. WPM = %s" % 
			(rhymelist[i][1][1],(name + "-1.wav."),wpm));	
		save_wav(language,(flags+(" -a "+DEFAULTRHYMEAMPLITUDE+" -p "#RHYME PART
			+DEFAULTRHYMEPITCH+" -s "+wpm)),rhymelist[i][1][1], (name + "-1")); 
		if (double):
			print("saving DOUBLED line \"%s\" as %s. WPM = %s" % 
				(rhymelist[i][1][1],(name + "-1-DOUBLE.wav."),wpm));
			save_wav(DOUBLELANGVOICE,(flags+(" -a "
				+DEFAULTDOUBLEAMPLITUDE +" -p "
				+DEFAULTDOUBLEPITCH+" -s "+wpm)),
				rhymelist[i][1][1], (name + "-1-DOUBLE")); #RHYME DOUBLE PART
	return wpm_list;

#Creates wav files based on the rhymelist from read_file2()
#Saves the first part and rhyming part separately as <name>-<line>-<0 or 1>
#Applies modifiers according to the arguments given in this, or the synthesize_
#lines()-function. Constructs a timing matrix for analyzing, and plays the 
#combined wav created.
def synthesize_and_compile2(song_name, options, clean=False):

	mbrola=options['mbrola']; #Not currently used here but meh
	augment=options['augment'];
	constant_WPM=options['constant_WPM'];
	double=options['double'];
	trim=options['trim'];
	start_silence=options['start_silence'];

	rhymelist=read_file2(song_name);
	if (augment):
		rhymelist=generate_phoneme_file(rhymelist, True, augment); 
	bpm=rhymelist[0];
	n_of_wavs = len(rhymelist);
	bar_length = 60.0/bpm*4.0;
	song_array=[];
	
	timing_matrix = [[0 for i in range(6)] for j in range(n_of_wavs-1)]; 

	wpm_list=synthesize_lines(song_name, rhymelist, DEFAULTLANGVOICE, 
		"",double,constant_WPM);#synthesize_lines2

	print("----/ COMPILING \\ ------");
	silence_penalty=0; #If silence couldn't be created, try to catch up with the
					   #next silence by substracting this! : OOOOO
	for i in range(1, n_of_wavs):		#BC BPM AS FIRST LINE
		if (trim): #Flag for trimming silence off of wavs
			print("\tTrimming line " + str(i)+"...");
			current_sample1 = trim_silence(song_name + "-" + str(i) + "-0",
				False);
			current_sample2 = trim_silence(song_name + "-" + str(i) + "-1",
				False);
			if (double):
				current_sample3 = trim_silence(song_name + "-" + str(i) 
					+ "-1-DOUBLE",False);
		else:
			current_sample1 = (song_name + "-" + str(i) + "-0");
			current_sample2 = (song_name + "-" + str(i) + "-1");
			if (double):
				current_sample3 = (song_name + "-" + str(i) + "-1-DOUBLE");
		if (double): #Flag for creating double tracking rhyme part
			print("\tCreating doubled rhyme...");
			delay=create_pause(DOUBLEDELAY,i,"silenceDELAY");
			delayed_double1=combine_wavs([current_sample2,delay],(song_name+"-"
				+str(i)+"-1-DELAY1-"),False);
			delayed_double2=combine_wavs([delay,current_sample3],(song_name+"-"
				+str(i)+"-1-DELAY2-"),False);
			current_sample2=mix_wav_files(delayed_double1,delayed_double2, 
				False, False);

		duration1 = get_sample_length(current_sample1,False);
		duration2 = get_sample_length(current_sample2,False);
		difference = bar_length-duration1-duration2;
		print("difference = " + str(difference));
		difference += silence_penalty; #CHECK IF THIS WORKS
		silence_penalty=0;
		print("difference2 = " + str(difference));
		print("Silence penalty = " + str(silence_penalty));
		if (not start_silence):	#Start the first line with first beat
			song_array.append(current_sample1);

		if difference>0:	#Should always be
			song_array.append(create_pause(difference,i));
		else:
			print("UNDERFULL SILENCE!");
			silence_penalty+=difference;

		if (start_silence):	#Start first line after silence
			song_array.append(current_sample1);	#SILENCE IN BEGINNING
				#Alternating these two might be good
				#
		song_array.append(current_sample2); 

		timing_matrix[i-1][0]=int(wpm_list[0][i-1]);
		timing_matrix[i-1][1]=int(wpm_list[1][i-1]);
		timing_matrix[i-1][2]=duration1;
		timing_matrix[i-1][3]=difference;
		timing_matrix[i-1][4]=duration2;
		timing_matrix[i-1][5]=silence_penalty;
	
	print_timing_matrix(timing_matrix);
	print("----/ PLAYING \\------");
	compiled_song = combine_wavs(song_array, song_name,True);
	print("Playback at " + str(bpm) + " BPM");
	print("Current modifiers: ");
	print_options(options);
	if (clean):
		clean_directory(compiled_song,False); #Don't move the result
	time_wav(compiled_song);

#Concatenates all the wavs in wav_array one after another into one file.
def combine_wavs(wav_array, song_name, echo=True):	#This works
	outfile = song_name + ".wav";
	infiles = [];
	data= [];

	for wav in wav_array:
		if ".wav" not in wav:
			infiles.append(wav + ".wav");
		else:
			infiles.append(wav);
	#print("Received wave array to combine");
	#print(infiles);

	for infile in infiles:
		w = wave.open(infile, 'rb')
		data.append( [w.getparams(), w.readframes(w.getnframes())]);
		w.close();

	#BINARY FOR WINDOWS ONLY???? works as is in ubuntu
	output = wave.open(outfile, 'wb')	
	output.setparams(data[0][0])
	output.writeframes(data[0][1])
	for i in range(len(infiles)-1):
		output.writeframes(data[i+1][1])
	output.close()

	if (echo):
		print("Combined lyrics saved as " + song_name + ".wav\n");
	return outfile.strip(".wav");


#Combines (mixes) two wave files into one.
def mix_wav_files(wav1_name, wav2_name, playback=True, echo=True, clean=False):
	directory="";
	if ("/" in wav2_name):
		s=wav2_name.split("/");
		directory = s[0]+"/";
		wav2_name=s[1];
	new_wav = wav1_name +"+"+ wav2_name;

	if (echo):
		print("Creating " + new_wav);
	try:
		w1 = wave.open(wav1_name+".wav",'rb');
		w2 = wave.open(directory+wav2_name+".wav",'rb');
		wav_mix = wave.open(new_wav+".wav", 'wb');
	except (IOError):
		print("ERROR OPENING FILE w1,w2 or newwav : D");
		return 0;

	#Combine until the shorter one runs out
	n_of_frames = min(w1.getnframes(),w2.getnframes());	
	samples1 = w1.readframes(n_of_frames);
	samples2 = w2.readframes(n_of_frames);

	samples1 = [samples1[i:i+2] for i in range(0, len(samples1), 2)];	
	samples2 = [samples2[i:i+2] for i in range(0, len(samples2), 2)];

	new_array=[];
	new_array2=[];

	for i in range(0,n_of_frames):
		unpacked_value1 = struct.unpack('<h', samples1[i]);#h=SHORT LITTLE ENDI
		unpacked_value2 = struct.unpack('<h', samples2[i]);#H=SHRT UNSIG LIT END
		unpacked_value3=(unpacked_value1[0]*1.2)/2+(unpacked_value2[0]*0.8)/2;
		#unpacked_array.append(int(unpacked_value3));
		new_array.append(struct.pack('<h', round(unpacked_value3)));
	
	for i in range(0, n_of_frames,2):
		new_array2.append(new_array[i]);
		if (i == n_of_frames-1):
			if (n_of_frames%2 is 0):#have to check if nframes is odd for bounds
				new_array2.append(new_array[i+1]);
		else:
			new_array2.append(new_array[i+1]);

	new_value_str = b''.join(new_array2);
	wav_mix.setparams((1, SAMPLEWIDTH, FRAMERATE, (n_of_frames), 
		'NONE', 'not compressed'))	#Default from espeak wavs
	wav_mix.writeframes(new_value_str);

	w1.close();
	w2.close();
	wav_mix.close();

	
	if (echo):
		print("\nMixed song saved as " + new_wav+".wav");
		if (clean):
			print("TO " + SONGDIR+"\n");
	if (clean):
		clean_directory(new_wav,True);
	if(playback):
		time_wav(SONGDIR+new_wav);
	
	return new_wav;

#Calculates the decibel values for chunks of samples and trims any silence
#from the file. Leaves one chunk of silence after a chunk with sound.
def trim_silence(song_name, echo=True):	#A bit clunky and hurried-sounding?
	if ".wav" not in song_name:
		wav = wave.open(song_name+".wav",'rb');
	else:
		wav = wave.open(song_name,'rb');
	n_of_frames=wav.getnframes();
	frame_array = wav.readframes(n_of_frames);
	
	chunksize=DBCHUNKSIZE;
	unpacked_array=[];
	samplechunks = [];
	cleaned_frames=[];	#Really should learn to use generators here
	new_array2=[];
	
	samples = [frame_array[i:i+2] for i in range(0, len(frame_array), 2)];

	for i in range(0,int(n_of_frames)):
		unpacked_value = struct.unpack('<H', samples[i])#h=SHORT LITTLE ENDIAN
		unpacked_array.append(int(unpacked_value[0]));	#is the cast necessary?

	samplechunks=[unpacked_array[i:i+chunksize] for i in range(0,
		len(unpacked_array),chunksize)];

#dbs=[20*math.log10(math.sqrt(mean(dotpower(chunk)))) for chunk in samplechunks]
	
	#THIS PART IS OK
	previous_chunk_added=False;
	for chunk in samplechunks:
		db=20.0*math.log10(math.sqrt(mean(dotpower(chunk))));
		if(db > 0):
			previous_chunk_added=True;
			for i in chunk:
				cleaned_frames.append(struct.pack('<H', i));
		else:
			if (previous_chunk_added):
				for i in chunk:
					cleaned_frames.append(struct.pack('<H', i));
			previous_chunk_added=False;
	for i in range(0, len(cleaned_frames),2):
		new_array2.append(cleaned_frames[i]);
		if (i == len(cleaned_frames)-1):
			if (len(cleaned_frames)%2 is 0):#have to check if nframes is odd 
				new_array2.append(cleaned_frames[i+1]);
		else:
			new_array2.append(cleaned_frames[i+1]);

	if (echo):
		print("Discarded frames for "+ str(song_name)+" = " + 
			str((len(frame_array)-len(cleaned_frames))) + 
			" From " + str(len(frame_array)));
	#TO HERE
	new_frames = b''.join(new_array2);
	new_name = song_name+"-TRIMMED.wav";
	new = wave.open(new_name,'wb');
	new.setparams((1, SAMPLEWIDTH, FRAMERATE, (len(new_frames)), 
		'NONE', 'not compressed'))	#Default from espeak wavs
	new.writeframes(new_frames);

	new.close();
	if (echo):
		print("Trimmed wav saved as "+new_name+"\n");
	return new_name;


#Creates empty wav-files with duration IN SECONDS. Names them with indexes
#that match the lyric wavs. Also able to name them differently with "name" arg
def create_pause(duration,index,name="silence"):	
	sample_length = int(round(duration*FRAMERATE)); 
	outputfile = name+str(index)+".wav"; 
	pause = wave.open(outputfile, 'w')
	pause.setparams((NCHANNELS, SAMPLEWIDTH, FRAMERATE, 0, 
		'NONE', 'not compressed'))	#Default from espeak wavs

	values = [];

	for i in range(0, sample_length):
		#value = random.randint(0, 32767)	#whitenoise
		packed_value = struct.pack('h', 0)	
		values.append(packed_value)


	value_str = b''.join(values);	
	pause.writeframes(value_str)

	pause.close()
	return outputfile.strip(".wav");	#Since most functions just want the name


############################# HELPER FUNCTIONS ################################

#Calculates the duration of wav by frames/framerate
def get_sample_length(input, echo=True): #gets length in seconds
	if ".wav" not in input:
		f = wave.open(input+".wav",'r');
	else:
		f = wave.open(input,'r');
	frames = f.getnframes()
	rate = f.getframerate()
	duration = frames / float(rate)
	f.close();
	#length = frames/float(framerate);
	if echo:
		print("Sample length (according to nframes/FPS) = " + str(duration));
	return duration;

#Measures the time between the start and end of playing the wave.
#aplay (or something else) produces a delay of approx. 150 ms
def time_wav(input): #input without .wav.
	start = time.time();
	if ".wav" not in input:
		execute("aplay -q %s.wav" % input);
	else:
		execute("aplay -q %s" % input);
	duration = time.time()-start;
	print("Duration of " + input + " (according to time) = " + str(duration));
	#get_sample_length(input, True);


#Translate lyrics into phonemes.
#If augment=True, augments the rhyming part with IPA accents
#before vowels and in the beginning of the word.
#Return_rhymelist=True parses the phonemes back into the same format
#as rhymelist and allows them to be used straight in synthesizing
def generate_phoneme_file(rhymelist,return_rhymelist=False,augment=True):
	print("Generating phoneme data...");
	bpm=rhymelist[0];
	phonemes=[];

	for line in rhymelist[1:]:
		if (line is not ""):
			first_part=line[1][0].strip(" ");
			rhyme_part=line[1][1].strip(" ");
			phonemes.append((str(speak("en+3","-x -q", first_part),
				encoding='UTF-8').strip(" \n"),
				str(speak("en+3","-x -q", rhyme_part),
				encoding='UTF-8').strip(" \n")));
		else:
			phonemes.append("","");

	print("GENERATED PHONEMES:");
	print(phonemes);

	if (augment):
		print("AUGMENTED PHONEMES:");
		augmented = augment_phonemes(phonemes);
		print(augmented);
		if (return_rhymelist):
			return reconstruct_rhymelist_from_phonemes(augmented,rhymelist);
		else:
			return augmented;

	if (return_rhymelist):
		return reconstruct_rhymelist_from_phonemes(phonemes,rhymelist);
	else:
		return phonemes;


#Reconstructs a usable rhymelist from phonemes to allow it to be used in 
#synthesis.
def reconstruct_rhymelist_from_phonemes(phonemes,rhymelist):
	print("Reconstructing rhymelist from phonemes...");
	new_rhymelist=[];
	new_rhymelist.append(rhymelist[0]);
	print(rhymelist[0]);
	#for line in phonemes:
	for line in range(len(phonemes)):
		first_part="".join(["[[",phonemes[line][0],"]]"]);
		second_part="[["+phonemes[line][1]+"]]";
		new_rhymelist.append((rhymelist[line+1][0],[first_part,second_part]));
	return new_rhymelist;


#Add a little oomph to the pronunciation
#Sounds like shit, research this
def augment_phonemes(phonemes):
	print("Augmenting phonemes...");
	vowels="AEIOUYÄÖaeiouyäö";
	phoneme_vowels="@30V";#Among other redundant stuff
	vowels=vowels+phoneme_vowels;
	aug=[];
	for line_tuple in phonemes:
		rhyme=line_tuple[1];
		if (rhyme is ""):
			aug.append(("",""));
		for char in rhyme[::-1]:	#Add accent only to the last vowel
			if char in vowels:
				part1=rhyme[0:rhyme.index(char)];
				part2=rhyme[rhyme.index(char):];
				#Accent the begin in addition to last vowel #NOW COMMENTED OUT!
				#new_tuple = (line_tuple[0],"".join(["'",part1  ,"'"  ,part2]));
				new_tuple = (line_tuple[0],"".join(["'",part1,part2]));
				line_tuple=new_tuple;
				#print("NEW rhyme = " + str(line_tuple[1]));
				aug.append(new_tuple);
				break;

	return aug;


#Prints metrics from the synthesis
def print_timing_matrix(timing_matrix):
	print("\n+-i--+-WPM-+->WPM+-Sample1-+-Silence-+-Sample2-+-S. Pen.-+");
	for i in timing_matrix:
		print("    {:2d} & {:3d} & {:3d} &{: .5f} &{: .5f} &{: .5f} \\\\ \\"
		+"hline".format((timing_matrix.index(i)+1),i[0],i[1],i[2],i[3],i[4]));
		#print("| {:2d} | {:3d} | {:3d} |{: .5f} |{: .5f} |{: .5f} |{: .5f} |"
			#.format(timing_matrix.index(i),i[0],i[1],i[2],i[3],i[4],i[5]));
	print("+----+-----+-----+---------+---------+---------+---------+\n");

#Print the synthesis parameters (toggleable in the main chooser)
def print_options(options):
	print("\nCURRENT FLAGS: mbrola="+str(options['mbrola'])
			+", augment="+str(options['augment'])
			+", constant_WPM="+str(options['constant_WPM'])
			+", double="+str(options['double'])
			+", trim="+str(options['trim'])
			+", start_silence="+str(options['start_silence']));


#Calculate the mean of an array. #Need the max(..,1) to prevent db calculations
#from failing.
def mean(a):
	return max(float(sum(a))/max(len(a),1.0),1);	

#Square every element in the array independently
def dotpower(a):
	#b = [i*i for i in a];?
	ar=[]
	for i in a:
		ar.append(i*i);
	return ar;

#Returns input from commandline or 0 if a valid "quitting character"
def get_input(quit_array):
	choice=input("\n");
	for s in quit_array:
		if choice is s:
			return 0;
	return choice;


################################# MAIN TEST LOOP ##############################
#A simple chooser to do various things
def main_loop(bpm):
	options={
	'mbrola':	   	False,	#get this to work from here
	'augment':    	True,	#Augment phonemefiles prior synthesis
	'constant_WPM':	True,	#Use constant WPM rather than dynamic
	'double':	    True,	#Double rhyming part using double tracking
	'trim':		    True,	#Trim the silence from wavs right after synthesis
	'start_silence':False}	#Add the silene in the beginning instead
	

	while (True):
		initialize(options); #Used mainly for updating the voices to/from mbrola
		"""		
		print("Listing synthesized wavs");
		list_files("",'wav');
		print("Listing beatfiles");
		list_files(BEATDIR,'wav');
		print("Listing lyricfiles");
		list_files(LYRICDIR,"-v '~'");
		break;
		"""

		print_options(options);
		print("[You can toggle these by inputting the name of flag!]");
		print("\nChoose your input: Pls no evil inputs). \"0\" to quit");
		print("1) Synthesize and compile \n2) Mix lyrics and beat\n"
			+"3) Create phoneme file");
		choice = input();

		if choice=="1": #Synthesize and compile
			list_files(LYRICDIR,"-v '~'");
			lyricfile = get_input(["0",""]);
			if (lyricfile is not 0):
				synthesize_and_compile2(lyricfile, options, True);

		elif choice=="2": #Mix lyrics and beat
			print("Specify two files to mix together. Separate with enter. "
				+"FIRST LYRICWAV THEN BEATWAV!!!");
			list_files("",'wav');
			firstfile = input("Synthesized lyrics:\n");
			list_files(BEATDIR,'wav');
			secondfile= input("Desired beat:\n");
			if (str(firstfile) == "" or str(firstfile) == "0"):
				continue;
			mix_wav_files(firstfile,BEATDIR+secondfile,True,True,True);
			#Flags: playback,echo,move

		elif choice=="3": #Generate phonemes
			list_lyric_files();
			lyricfile = input("\n");
			if (str(lyricfile) == "" or str(lyricfile) == "0"):
				continue;
			generate_phoneme_file(read_file2(lyricfile), False, True);

		elif choice in options:
			options[choice] = not options[choice]; #Should toggle bools
			print(str(choice)+" toggled -> " + str(options[choice]));

		elif choice=="0": #Quit
			return 0;

		elif choice=="4":
			print("Specify two files to mix together. Separate with enter. "
				+"FIRST LYRICWAV THEN BEATWAV!!!");
			list_files("",'wav');
			firstfile = input("Synthesized lyrics:\n");
			list_files(BEATDIR,'wav');
			secondfile= input("Desired beat:\n");
			if (str(firstfile) == "" or str(firstfile) == "0"):
				continue;
			t=synthesize_raw(firstfile, True);
			mix_wav_files(t,BEATDIR+secondfile,True,True,True);

		else:
			print("Choice not found, please try again (0 or Ctrl+C to quit)");


######################### UNNECESSARY STUFF #########################

def create_drums():		#Find phonemes that sound like drums!
	save_wav("en+f1","-p 50","sch","hihat");
	save_wav("fi","-p 10","[[k]]","snare_rim");
	save_wav("en+m3","-p 5","[[p]]","snare");
	#save_wav("en","","")
	#http://www.mcld.co.uk/beatboxalphabet/
	#Well what do you know this has been done
	
def play_drums(between_beats):
	print("STARTING BEAT");
	print("time between beats: %f" % between_beats);
	create_drums();
	t=0.1;
	for i in range(30):
		start = time.time();
		#print(time.time());
		play("snare");
		time.sleep(max(0,((start+between_beats)-time.time())));
		#print(time.time());
		play("hihat");
		time.sleep(max(0,((start+2*between_beats)-time.time())));
		#print(time.time());
		play("snare_rim");
		time.sleep(max(0,((start+3*between_beats)-time.time())));
		#print(time.time());
		play("hihat");
		time.sleep(max(0,((start+4*between_beats)-time.time())));

def visualize_bars(): # do some visualization of triggering of samples in bars?
	print("4/4: |----|----|----|----|");

def sequencer(bar): #OMG DO A TEXTUAL SEQUENCER TO TRIGGER SAMPLES?dont digress
	bar.replace("|",""); #remove bar lines 
	for char in bar:
		pass;




main_loop(95);	#Simple testing interface



"""	OLD FILE CHOOSERS
#To list lyric files for the file chooser
def list_lyric_files():	# ignore directories. use find?
	print("Possible lyric files found in "+ LYRICDIR +":");
	s = str(execute("ls "+LYRICDIR+" | grep -v '\.' | grep -v '~'"));
	s = s[2:-1].replace("\\n","\n");
	#USE str(s,encoding='UTF-8');
	print("+----------");
	for line in s.splitlines():
		print("| "+line);
	print("+----------");

#To list wave files for the file chooser
def list_wav_files():		#CLEAN THIS FUNCTION!!!!!!!!!!!!!!!!!!!!!!!!!!
	print("Synthesized songs found (only the song name):")
	print("+----------");
	s = str(execute("ls -p | grep -v '/$' | grep 'wav'"));
	s = s[2:-1].replace("\\n","\n");
	#print(s);	
	for line in s.splitlines():
		print("| "+line.strip(".wav"));
	print("+----------");

#To list wave files for the file chooser
def list_beat_files():		#CLEAN THIS FUNCTION!!!!!!!!!!!!!!!!!!!!!!!!!!
	print("Instrumental beats found in in "+BEATDIR+":")
	print("+----------");
	s = str(execute("ls -p "+BEATDIR+" | grep -v '/$' | grep 'wav'"));
	s = s[2:-1].replace("\\n","\n");
	#print(s);	
	for line in s.splitlines():
		print("| "+line.strip(".wav"));
	print("+----------");




"""


