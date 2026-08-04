VERSION 5.00
Object = "{F9043C88-F6F2-101A-A3C9-08002B2F49FB}#1.2#0"; "COMDLG32.OCX"
Begin VB.Form Form1 
   BorderStyle     =   1  'Fest Einfach
   Caption         =   "Hubbard 2 Goattracker converter v1.2"
   ClientHeight    =   5445
   ClientLeft      =   45
   ClientTop       =   330
   ClientWidth     =   7830
   BeginProperty Font 
      Name            =   "Tahoma"
      Size            =   8.25
      Charset         =   0
      Weight          =   400
      Underline       =   0   'False
      Italic          =   0   'False
      Strikethrough   =   0   'False
   EndProperty
   Icon            =   "h2g.frx":0000
   LinkTopic       =   "Form1"
   MaxButton       =   0   'False
   ScaleHeight     =   5445
   ScaleWidth      =   7830
   StartUpPosition =   2  'Bildschirmmitte
   Begin VB.PictureBox Picture1 
      BackColor       =   &H80000018&
      Height          =   975
      Left            =   0
      Picture         =   "h2g.frx":030A
      ScaleHeight     =   915
      ScaleWidth      =   7755
      TabIndex        =   7
      Top             =   0
      Width           =   7815
   End
   Begin MSComDlg.CommonDialog FS 
      Left            =   480
      Top             =   6000
      _ExtentX        =   847
      _ExtentY        =   847
      _Version        =   393216
   End
   Begin VB.Frame Frame4 
      Height          =   4455
      Left            =   0
      TabIndex        =   0
      Top             =   960
      Width           =   7815
      Begin VB.Frame Frame1 
         Caption         =   "Drag .SID file into this box"
         Height          =   1215
         Left            =   120
         OLEDropMode     =   1  'Manuell
         TabIndex        =   3
         Top             =   120
         Width           =   7575
         Begin VB.CommandButton Command2 
            Caption         =   "Browse"
            Height          =   495
            Left            =   6480
            TabIndex        =   6
            Top             =   600
            Width           =   975
         End
         Begin VB.CommandButton Command1 
            Caption         =   "Load"
            Height          =   495
            Left            =   120
            TabIndex        =   5
            Top             =   600
            Width           =   6255
         End
         Begin VB.TextBox Text1 
            Height          =   285
            HideSelection   =   0   'False
            Left            =   120
            OLEDropMode     =   1  'Manuell
            TabIndex        =   4
            Top             =   240
            Width           =   7335
         End
      End
      Begin VB.Frame Frame2 
         Caption         =   "Info"
         Height          =   2895
         Left            =   120
         TabIndex        =   1
         Top             =   1440
         Width           =   7575
         Begin VB.TextBox TextStatus 
            BackColor       =   &H80000010&
            BeginProperty Font 
               Name            =   "Lucida Console"
               Size            =   8.25
               Charset         =   0
               Weight          =   400
               Underline       =   0   'False
               Italic          =   0   'False
               Strikethrough   =   0   'False
            EndProperty
            ForeColor       =   &H80000014&
            Height          =   2535
            Left            =   120
            MultiLine       =   -1  'True
            ScrollBars      =   2  'Vertikal
            TabIndex        =   2
            Top             =   240
            Width           =   7335
         End
      End
   End
End
Attribute VB_Name = "Form1"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
'H2G
'Written by Stilianos (Stello) Doussis in August 2005 in VB6
Option Explicit
Dim SIDfile(65536) As Long
Dim SIDlenght As Long
Dim SIDname As String
Dim SIDauthor As String
Dim SIDreleased As String
Dim SIDsubtunes As Long
Dim SIDloadaddr As Long
Dim SIDhlenght As Long

Dim Goatfile(999999) As Byte
Dim Goatfl As Long
Dim GoatTableWave(256) As Byte
Dim GoatTablePulse(256) As Byte
Dim GoatTracksMax As Long
Dim GoatTracks(256, 256) As Long     'Track number, Track Data (in pos 0 is the lenght of this track stored)

Dim GoatPatternMax As Long
Dim GoatPLength(256) As Long
Dim GoatPattern(256, 8192) As Long 'Pattern number, Pattern Position, 0=Note, 1=Instrument, 2=Command (0-f), 3=Command Value

Dim SIDRHreadTrackVersion As Long
Dim SIDRHinstrStart As Long
Dim SIDRHinstrUsed As Long
Dim SIDRHtrackVoices As Long
Dim SIDRHtrackSelector As Boolean
Dim SIDRHtrackHi As Long
Dim SIDRHtrackLo As Long
Dim SIDRHPatternHi As Long
Dim SIDRHPatternLo As Long
Dim SIDRHPattternUsed As Long

Private Sub Form_Load()
    SIDhlenght = &H7F
    ShowAboutText
    DoShow True
End Sub
Private Sub ShowAboutText()
    Dim txt As String
    txt = "H2G CONVERTER v1.2" + vbCrLf
    txt = txt + "------------------" + vbCrLf
    txt = txt + "This program converts .SID files created by Rob Hubbard to Bitops Goattracker (v2.34 and up) .SNG fileformat." + vbCrLf + vbCrLf
    txt = txt + "It is experimental and meant to be educational, it enables you to view Rob Hubbards tunes (some, not all!), to play original Tracks/Pattern/Instruments back in Goattracker. Treat converted songs as his intellectual property. " + vbCrLf + vbCrLf
    txt = txt + "A perfect conversion is impossible. Rob Hubbard's music player and Goattracker are totally different music file formats, algorithms and concepts, some RH tunes are not convertable to Goattracker at all." + vbCrLf + vbCrLf
    txt = txt + "Due to lack of time, i decided to discontinue further development. The provided source code can be modified and republished and used freely by others without any notice. Please do not contact me for any technical problems you might experience using it." + vbCrLf + vbCrLf
    txt = txt + vbCrLf + "WRITTEN IN AUG/2005 BY stello_doussis(AT)yahoo.com" + vbCrLf
    TextStatus.Text = txt
End Sub
Private Sub DoShow(DoStat As Boolean)
    Text1.Enabled = DoStat
    Command1.Enabled = DoStat
    Command2.Enabled = DoStat
    Frame1.Enabled = DoStat
End Sub

Private Sub Picture1_Click()
    ShowAboutText
End Sub
Private Sub Text1_OLEDragDrop(Data As DataObject, Effect As Long, Button As Integer, Shift As Integer, X As Single, y As Single)
    Text1.Text = Data.Files(1)
    loadfile
End Sub
Private Sub Frame1_OLEDragDrop(Data As DataObject, Effect As Long, Button As Integer, Shift As Integer, X As Single, y As Single)
    Text1.Text = Data.Files(1)
    loadfile
End Sub
Private Sub Command1_Click()
    loadfile
End Sub
Private Sub AddTextS(AddText As String)
    TextStatus.Text = TextStatus.Text + AddText + vbCrLf
    TextStatus.SelStart = Len(TextStatus.Text)
End Sub
Private Sub loadfile()
    Dim fslen As Long
    Dim fsff As Long
    Dim b1 As Byte
    Dim b2 As Byte
    Dim b3 As Byte
    Dim b4 As Byte
    Dim vwaveforms(99) As Long
    Dim instrused As Long
    Dim i As Long
    Dim so As Long
    Dim i2 As Long
    Dim svcompare As Long
    Dim DoRip As Boolean
    
    DoShow False
    DoEvents
    vwaveforms(0) = &H0
    vwaveforms(1) = &H1
    vwaveforms(2) = &H9
    vwaveforms(3) = &H11
    vwaveforms(4) = &H13
    vwaveforms(5) = &H15
    vwaveforms(6) = &H17
    vwaveforms(7) = &H21
    vwaveforms(8) = &H23
    vwaveforms(9) = &H25
    vwaveforms(10) = &H27
    vwaveforms(11) = &H41
    vwaveforms(12) = &H43
    vwaveforms(13) = &H45
    vwaveforms(14) = &H47
    vwaveforms(15) = &H51
    vwaveforms(16) = &H53
    vwaveforms(17) = &H55
    vwaveforms(18) = &H57
    vwaveforms(19) = &H81
    SIDname = ""
    SIDauthor = ""
    SIDreleased = ""
    SIDloadaddr = 0
    SIDloadaddr = 0
    
    
    TextStatus.Text = ""
    AddTextS "Loading:" + vbCrLf + Text1.Text
    
  '''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''''  On Error GoTo fileError
    
    fsff = FreeFile
    Open Text1.Text For Binary As #fsff
    fslen = LOF(fsff)
    If fslen >= 65536 Then GoTo fileError
    Get #fsff, &H1, b1
    Get #fsff, &H2, b2
    Get #fsff, &H3, b3
    Get #fsff, &H4, b4
    
    If b2 <> Asc("S") Then GoTo fileError
    If b3 <> Asc("I") Then GoTo fileError
    If b4 <> Asc("D") Then GoTo fileError
    AddTextS "------------------------------------------------------SID INFO---"
    'get sidname
    SIDname = ""
    For i = &H17 To &H17 + &H1F
        Get #fsff, i, b1
        If b1 <> 0 Then SIDname = SIDname + Chr(b1)
    Next i
    AddTextS "SID Name....: '" + SIDname + "'"

    'get author
    SIDauthor = ""
    For i = &H37 To &H37 + &H1F
        Get #fsff, i, b1
        If b1 <> 0 Then SIDauthor = SIDauthor + Chr(b1)
    Next i
    AddTextS "SID Author..: '" + SIDauthor + "'"

    'get release year/copyright
    SIDreleased = ""
    For i = &H57 To &H57 + &H1F
        Get #fsff, i, b1
        If b1 <> 0 Then SIDreleased = SIDreleased + Chr(b1)
    Next i
    AddTextS "SID Released: '" + SIDreleased + "'"

    'get startaddress
    Get #fsff, &H7D, b1
    Get #fsff, &H7E, b2
    SIDloadaddr = b2
    SIDloadaddr = SIDloadaddr * 256
    SIDloadaddr = SIDloadaddr + b1
    AddTextS "SID Loadaddr: $" + Hex(SIDloadaddr)

    'get subtunes
    Get #fsff, &H10, b1
    SIDsubtunes = b1
    AddTextS "SID Subtunes: $" + Hex(SIDsubtunes)
    
    'load entire file
    For i = 1 To fslen
        Get #fsff, i, b1
        SIDfile(i - 1) = b1
    Next i
    SIDlenght = fslen
    Close #fsff
    
    AddTextS "-----------------------------------------------------SEARCHING---"
    SIDRHinstrStart = -1
    SIDRHinstrUsed = -1
    SIDRHtrackHi = -1
    SIDRHtrackLo = -1
    SIDRHPatternHi = -1
    SIDRHPatternLo = -1




    'find instruments start
                    i = SSearchfile("BD ?? ?? 99 02 D4 48 BD ?? ?? 99 03 D4")    'Chimera
    If i <= -1 Then i = SSearchfile("BD ?? ?? 99 02 D4 BD ?? ?? 99 03 D4")       'ACE2
    If i <= -1 Then i = SSearchfile("BD ?? ?? 99 ?? ?? 48 BD ?? ?? 99 ?? ?? 48") 'IK+
    If i <= -1 Then
        AddTextS "*** CAN'T FIND INSTRUMENTS ***"
        GoTo FindSubSongs
    End If
    b1 = SIDfile(i + 1)
    b2 = SIDfile(i + 2)
    i = b2
    i = i * 256
    i = i + b1
    SIDRHinstrStart = i - SIDloadaddr + SIDhlenght - 1
    AddTextS "Found Instruments at....: $" + Hex(i)
    'find instruments end (instrument must begin with 1x, 2x, 4x, 5x, 8x)
    i = SIDRHinstrStart + 2
    instrused = 0
    Do
        'waveform
        svcompare = 0
        For i2 = 0 To 19
            If SIDfile(i) = vwaveforms(i2) Then svcompare = svcompare + 1
        Next i2
        If svcompare <= 0 Then
            Exit Do
        End If
        i = i + 8
        If i >= SIDlenght Then
            i = SIDRHinstrStart + 2 + 8
            AddTextS "*** CAN'T FIND INSTRUMENT-END, SET TO DEFAULT (1 INSTRUMENT) ***"
            Exit Do
        End If
        instrused = instrused + 1
    Loop
    AddTextS "Instruments used........: $" + Hex(instrused)
    SIDRHinstrUsed = instrused
   
    
FindSubSongs:
    'find subsongs/tracks start
    SIDRHtrackVoices = 3
    so = 3
                    i = SSearchfile("D0 ?? BD ?? ?? 85 ?? BD ?? ?? 85 ?? DE ?? ?? 30 ?? 4C"):        'IK+ / Warhawk   'simple
    If i <= -1 Then i = SSearchfile("D0 ?? BD ?? ?? 85 ?? BD ?? ?? 85 ?? D6 ?? 30 ?? 4C")            'Mega Apocalypse 'supports transpose in tracklist
    If i <= -1 Then i = SSearchfile("D0 ?? BD ?? ?? 85 ?? BD ?? ?? 85 ?? E0 ?? D0 ?? CE")            'Ricochet
    If i <= -1 Then i = SSearchfile("8E ?? ?? A8 BD ?? ?? 85 ?? BD ?? ?? 85 ?? BD ?? ?? F0"): so = 5 'Hollywood or bust
    If i <= -1 Then i = SSearchfile("8D ?? ?? A8 BD ?? ?? 85 ?? BD ?? ?? 85 ?? DE ?? ?? 30"): so = 5 'Harvey Smith Show Jumper
    i2 = i
    If i <= -1 Then
        AddTextS "*** CAN'T FIND TRACKS/SUBSONGS ***"
        GoTo FindTrackSelector
    End If
    'tracks LO
    b1 = SIDfile(i + so)
    b2 = SIDfile(i + so + 1)
    i = b2
    i = i * 256
    i = i + b1
    AddTextS "Found Tracks LO at......: $" + Hex(i)
    SIDRHtrackLo = i - SIDloadaddr + SIDhlenght - 1
    'tracks HI
    i = i2
    b1 = SIDfile(i + so + 5)
    b2 = SIDfile(i + so + 6)
    i = b2
    i = i * 256
    i = i + b1
    AddTextS "Found Tracks HI at......: $" + Hex(i)
    SIDRHtrackHi = i - SIDloadaddr + SIDhlenght - 1

FindTrackSelector:
    'search if trackselector exists
    'if yes, then use SIDRHtrackLo as startaddress and set SIDRHtrackSelector=True
    SIDRHtrackSelector = False
    so = 6
                    i = SSearchfile("18 6D ?? ?? AA BD ?? ?? 99 ?? ?? E8 C8 C0 06") 'Rasputin '$CF6B
    If i <= -1 Then
                    i = SSearchfile("8A 0A 0A AA BD ?? ?? 99 ?? ?? E8 C8 C0 04") 'Human Race '$B129
                    If i >= 1 Then
                        so = 5
                        SIDRHtrackVoices = 2
                        AddTextS "'Human Race' player (2 voices) detected."
                    End If
    End If
    If i <= -1 Then
        'AddTextS "No music selector found, might be not needed."
        GoTo FindPattern
    End If
    SIDRHtrackSelector = True
    b1 = SIDfile(i + so)
    b2 = SIDfile(i + so + 1)
    i = b2
    i = i * 256
    i = i + b1
    AddTextS "Found Music selector....: $" + Hex(i)
    SIDRHtrackLo = i - SIDloadaddr + SIDhlenght - 1
    SIDRHtrackHi = SIDRHtrackLo + SIDRHtrackVoices
    
FindPattern:
    'find pattern
    so = 11
                    i = SSearchfile("9D ?? ?? 4C ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D")   'LastV8 $80b1
    If i <= -1 Then i = SSearchfile("9D ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D"): so = 8    'Delta
    If i <= -1 Then i = SSearchfile("4C ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? BC ?? ?? A9"): so = 8 'Battle of Britain $8051
    If i <= -1 Then i = SSearchfile("4C ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 95"): so = 8    'Samantha Fox $7091
    If i <= -1 Then i = SSearchfile("20 ?? ?? 4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 9D"): so = 8    'SaboteurII $64bd
    If i <= -1 Then i = SSearchfile("4C ?? ?? A8 B9 ?? ?? 85 ?? B9 ?? ?? 85 ?? A9 ?? 95"): so = 5             'Mega Apocalypse $4b30 ' supports track transpose
    If i <= -1 Then
        AddTextS "*** CAN'T FIND PATTERN ***"
        GoTo FindPlayerVersion
    End If

    i2 = i
    'pattern LO
    b1 = SIDfile(i + so)
    b2 = SIDfile(i + so + 1)
    i = b2
    i = i * 256
    i = i + b1
    AddTextS "Found Pattern LO at.....: $" + Hex(i)
    SIDRHPatternLo = i - SIDloadaddr + SIDhlenght - 1
    'pattern HI
    i = i2
    b1 = SIDfile(i + so + 5)
    b2 = SIDfile(i + so + 6)
    i = b2
    i = i * 256
    i = i + b1
    AddTextS "Found Pattern HI at.....: $" + Hex(i)
    SIDRHPatternHi = i - SIDloadaddr + SIDhlenght - 1
    SIDRHPattternUsed = (SIDRHPatternHi - SIDRHPatternLo) - 1
    AddTextS "Pattern used............: $" + Hex(SIDRHPattternUsed)

FindPlayerVersion:
    SIDRHreadTrackVersion = &HFF
                    i = SSearchfile("BC ?? ?? B1 ?? C9 FF F0 ?? C9 FE"): If i >= 1 Then SIDRHreadTrackVersion = 0                         'TRACKS: no transpose, $FE=end, $FF=Repeat (Warhawk...)
    If i <= -1 Then i = SSearchfile("BC ?? ?? B1 ?? C9 FE D0 ?? 4C ?? ?? C9 FF"): If i >= 1 Then SIDRHreadTrackVersion = 1                'TRACKS: no transpose, $FE=end, $FF=Repeat (Last V8...)
    If i <= -1 Then i = SSearchfile("BC ?? ?? B1 ?? 10 ?? C9 FF F0 ?? C9 FE F0"): If i >= 1 Then SIDRHreadTrackVersion = 2                'TRACKS: no transpose, $FE=end, $FF=Repeat (Auf Wiedersehen Monty...)
    If i <= -1 Then i = SSearchfile("B4 ?? B1 ?? C9 FF F0 ?? C9 FE D0"): If i >= 1 Then SIDRHreadTrackVersion = 3                         'TRACKS: no transpose, $FE=end, $FF=Repeat (Samantha Fox Strip Poker...)
    If i <= -1 Then i = SSearchfile("BC ?? ?? B1 ?? 10 ?? A9 ?? 9D ?? ?? 9D ?? ?? 9D"): If i >= 1 Then SIDRHreadTrackVersion = 4          'TRACKS: no transpose, $FF=Repeat (ACE 2...)
    If i <= -1 Then i = SSearchfile("BC ?? ?? B1 ?? C9 FF D0 ?? A9 ?? 9D ?? ?? 9D ?? ?? 9D"): If i >= 1 Then SIDRHreadTrackVersion = 5    'TRACKS: no transpose, $FF=Repeat (Battle of Britain...)
    If i <= -1 Then i = SSearchfile("B4 ?? B1 ?? 10 ?? C9 FF F0 ?? 29 7F"): If i >= 1 Then SIDRHreadTrackVersion = 6                      'TRACKS: Transpose >$80 = +  / <$FE = -  / $FF=Repeat (Mega Apocalypse)
    If i <= -1 Then i = SSearchfile("BC ?? ?? B1 ?? 10 ?? C9 FF F0 ?? 29 7F"): If i >= 1 Then SIDRHreadTrackVersion = 7                   'TRACKS: Transpose >$80 = +  / <$FE = -  / $FF=Repeat (IK+)
    AddTextS "Player Trackread version: " + Hex(SIDRHreadTrackVersion)

FindEnd:
    DoRip = True
    AddTextS "--------------------------------------------------------STATUS---"
    If SIDRHtrackLo <= 0 Or SIDRHtrackHi <= 0 Then DoRip = False
    If SIDRHPatternLo <= 0 Or SIDRHPatternHi <= 0 Then DoRip = False
    If DoRip = False Then
        AddTextS "*** NO HUBBARD PLAYER DETECTED, CAN'T CONVERT, ABORTING ***"
    Else
        AddTextS "*** HUBBARD PLAYER DETECTED, CONVERTING ***"
        AddTextS "----------------------------------------------------CONVERTING---"
        AddTextS "Please wait..."
        GoatClear
        GoatConvertTracks
        GoatConvertPattern
        GoatSave
        AddTextS vbCrLf + "*** READY  ***"
    End If
    GoTo allEnd
fileError:
    Close #fsff
    AddTextS vbCrLf + "*** AN ERROR OCCURED ***" + vbCrLf + "*** CHECK FILENAME/PATH - ONLY SID/PSID FILES SUPPORTED ***"
    AddTextS vbCrLf + "*** NO FILE SAVED ***"
allEnd:
    DoShow True
End Sub
Private Sub GoatSave()
    Dim fslen As Long
    Dim fsff As Long
    Dim b1 As Byte
    Dim b2 As Byte
    Dim i As Long
    Dim i2 As Long
    Dim i3 As Long
    Dim i4 As Long
    Dim fileAndPath As String
    Dim addr As Long
    Dim iName As String
    Dim iStr As String
    Dim WTableStart As Long
    Dim PTableStart As Long
    Dim ArpStyle As Long
    Dim ArpNote As Long
    Dim ArpSetkeybit As Long
   

    FS.CancelError = True
    FS.DialogTitle = "Save Goattracker File"
    FS.Flags = cdlOFNHideReadOnly + cdlOFNNoChangeDir + cdlOFNFileMustExist + cdlOFNOverwritePrompt
    FS.Filter = "Goattracker Song (*.sng)|*.sng|All Files (*.*)|*.*"
    FS.FilterIndex = 0
    FS.CancelError = False
    FS.FileName = SIDname + ".sng"
    FS.ShowSave
    fileAndPath = FS.FileName
    If fileAndPath = "" Then Exit Sub
    
    If FileExist(fileAndPath) = True Then Kill (fileAndPath)

    fsff = FreeFile
    Open fileAndPath For Binary As #fsff
    For i = 0 To &H63
        b1 = Goatfile(i)
        Put #fsff, i + 1, b1
    Next i
    'write sidsubtune numbers
    b1 = SIDsubtunes
    Put #fsff, , b1

    'write track data
    For i = 0 To GoatTracksMax - 1
        b1 = GoatTracks(i, 0) - 2
        Put #fsff, , b1
        For i2 = 1 To (GoatTracks(i, 0) - 1)
            b1 = GoatTracks(i, i2)
            Put #fsff, , b1
        Next i2
    Next i
    
    'Write Instruments
    'Increase Instrument number, Instrument 1 has always to be empty
    SIDRHinstrUsed = SIDRHinstrUsed + 1
    If SIDRHinstrUsed >= 50 Then SIDRHinstrUsed = 50
    b1 = SIDRHinstrUsed
    Put #fsff, , b1
    'First Instrument=Empty
        b1 = &H0
        Put #fsff, , b1 '1 AD
        Put #fsff, , b1 '2 SR
        b1 = &H1
        Put #fsff, , b1 '3 Wavetable
        Put #fsff, , b1 '4 Pulsetable
        b1 = &H0
        Put #fsff, , b1 '5 Filtertable
        Put #fsff, , b1 '6 Vibrato Delay
        Put #fsff, , b1 '7 Vibrato Speed/Dep
        b1 = &H2
        Put #fsff, , b1 '8 GateOff Timer
        b1 = &H9
        Put #fsff, , b1 '9 Hardreset/1stWave
        
        WTableStart = 6
        PTableStart = 3
        
        iName = iStr + "Clear Voice"
        For i3 = 1 To Len(iName)
            b1 = Asc(Mid(iName, i3, 1))
            Put #fsff, , b1                    'Instrument Name
        Next i3
        b1 = &H0
        For i3 = 0 To (&HF - Len(iName))
            Put #fsff, , b1                    'Instrument Name
        Next i3

    'Write Instrument Data
    For i = 0 To SIDRHinstrUsed - 2
        i2 = i * 8
        b1 = SIDfile(SIDRHinstrStart + i2 + 3) '1 AD
        Put #fsff, , b1
        b1 = SIDfile(SIDRHinstrStart + i2 + 4) '2 SR
        'check if S is bigger than F, if yes, change it to E, othewise some notes are not played
        'in goattracker using hardsid or real SID
        If b1 >= &HF0 Then
            b1 = b1 And &HEF 'mask last bit of first nibble (&SSSXRRRR (S=Sustain, R=Release, X=Cut this bit out)
        End If

        Put #fsff, , b1
        b1 = (i * 5) + WTableStart
        Put #fsff, , b1                        '3 Wavetable
        b1 = (i * 2) + PTableStart
        Put #fsff, , b1                        '4 Pulsetable
        b1 = &H0
        Put #fsff, , b1                        '5 Filtertable
        Put #fsff, , b1                        '6 Vibrato Delay
        Put #fsff, , b1                        '7 Vibrato Speed/Dep
        b1 = &H2
        Put #fsff, , b1                        '8 GateOff Timer
        b1 = &H9
        Put #fsff, , b1                        '9 Hardreset/1stWave
        
        iStr = FormHex(i + 2)
        iName = iStr + ":"
        iStr = FormHex(SIDfile(SIDRHinstrStart + i2 + 5))
        iName = iName + iStr + "-"
        iStr = FormHex(SIDfile(SIDRHinstrStart + i2 + 6))
        iName = iName + iStr + "-"
        iStr = FormHex(SIDfile(SIDRHinstrStart + i2 + 7))
        iName = iName + iStr
        For i3 = 1 To Len(iName)
            b1 = Asc(Mid(iName, i3, 1))
            Put #fsff, , b1                    'Instrument Name
        Next i3
        b1 = &H0
        For i3 = 0 To (&HF - Len(iName))
            Put #fsff, , b1                    'Instrument Name
        Next i3
    Next i
    
    'Write Instruments - Wavetable
    b1 = ((SIDRHinstrUsed) * 5)
    Put #fsff, , b1
    'Write Instrument1-'Empty' (LEFT side)
    b1 = &H9
    Put #fsff, , b1
    b1 = &HFF
    Put #fsff, , b1
    b1 = &H0
    Put #fsff, , b1
    Put #fsff, , b1
    Put #fsff, , b1
    'Instrument Data Wavetable
    For i = 0 To SIDRHinstrUsed - 2
        i2 = i * 8
        'If Bit1 set then set in 2nd Tick Noise sound
        ArpStyle = SIDfile(SIDRHinstrStart + i2 + 7)
        '%HGFEDCBA
        '%     001 = Hubbard TomTom sound (incl. Noise in 2nd Tick) (pitchbend)
        '%     100 = Arpeggio (get values fom %HGFE)
        '%     101 = Arpeggio + Noise in 2nd Tick
        '%    ?    = Unknown
        '%HGFE     = 2 Frame Arpeggio, Frame1 = original note, Frame2 = Original Note + $0C(1 Octave) - value %HGFE
        'ArpSetkeybit = (ArpStyle And 4) / 2 / 2 'Bit 3 of Arpstyle indicates if keybit is set for instruments entire lenght
        If (ArpStyle And 1) = 1 Then
            ArpSetkeybit = 0
        End If
        If (ArpStyle And 1) = 0 Then
            ArpSetkeybit = 1
        End If
        
        '1st Tick Wavetable
        b1 = SIDfile(SIDRHinstrStart + i2 + 2)
        Put #fsff, , b1
        
        '2nd Tick Wavetable
        If (ArpStyle And 1) = 1 Then
            b1 = &H80 Or ArpSetkeybit                     '2nd Tick: Noise Waveform
            Put #fsff, , b1
        Else
            b1 = SIDfile(SIDRHinstrStart + i2 + 2) And 254 Or ArpSetkeybit
            Put #fsff, , b1
        End If
        
        '3rd - 5th Tick Wavetable
        b1 = SIDfile(SIDRHinstrStart + i2 + 2) And 254 Or ArpSetkeybit
        If (ArpStyle And 4) = 4 Then
            Put #fsff, , b1                                '
            Put #fsff, , b1
            b1 = &HFF                                      'Jump OR End Mark
            Put #fsff, , b1
        Else
            Put #fsff, , b1
            b1 = &HFF
            Put #fsff, , b1
            Put #fsff, , b1
        End If
        
    Next i
    'Write Instrument1-'Empty' Wavetable (RIGHT side)
    b1 = &H0
    Put #fsff, , b1
    Put #fsff, , b1
    Put #fsff, , b1
    Put #fsff, , b1
    Put #fsff, , b1
    'Instrument Data Wavetable (RIGHT side)
    For i = 0 To SIDRHinstrUsed - 2
        i2 = i * 8
        ArpStyle = SIDfile(SIDRHinstrStart + i2 + 7)
        '%HGFEDCBA
        '%     001 = Hubbard TomTom sound (incl. Noise in 2nd Tick) (pitchbend)
        '%     100 = Arpeggio (get values fom %HGFE)
        '%     101 = Arpeggio + Noise in 2nd Tick
        '%    ?    = Unknown
        '%HGFE     = 2 Frame Arpeggio, Frame1 = original note, Frame2 = Original Note - value %HGFE, then loop back to Frame1
        ArpNote = (ArpStyle And &HF0) / 2 / 2 / 2 / 2
        If ArpNote = 0 Then ArpNote = &H74
        
        
        '1st Tick, Note
        b1 = &H0
        Put #fsff, , b1

        '2nd Tick Note
        If ((ArpStyle And 1) = 1) Or ((ArpStyle And 4) = 1) Then
            b1 = &H80 - ArpNote
            Put #fsff, , b1
        Else
            b1 = &H0
            Put #fsff, , b1
        End If
        
        '3rd - 5th Tick Note
        If (ArpStyle And 4) = 4 Then
            b1 = &H0
            Put #fsff, , b1                                       '
            b1 = &H80 - ArpNote
            Put #fsff, , b1
            b1 = ((i + 2) * 5) - 2 'Jump TO
            Put #fsff, , b1
        Else
            b1 = &H0
            Put #fsff, , b1
            Put #fsff, , b1
            Put #fsff, , b1
        End If
    Next i
    
    'Write Instruments - Pulsetable
    b1 = (SIDRHinstrUsed * 2)
    Put #fsff, , b1
    b1 = &H80
    Put #fsff, , b1
    b1 = &HFF
    Put #fsff, , b1
    For i = 0 To SIDRHinstrUsed - 2
        i2 = i * 8
        b1 = SIDfile(SIDRHinstrStart + i2 + 1) '1 Pulse Hi
        b1 = b1 Or &H80                        '  Set 8 Bit on to set pulse value
        Put #fsff, , b1
        b1 = &HFF
        Put #fsff, , b1                        '3 Mark end
    Next i
    b1 = &H0
    Put #fsff, , b1
    Put #fsff, , b1
    For i = 0 To SIDRHinstrUsed - 2
        i2 = i * 8
        b1 = SIDfile(SIDRHinstrStart + i2 + 0) '1 Pulse Lo
        Put #fsff, , b1                        '2 No Transpose
        b1 = &H0
        Put #fsff, , b1                        '4 Mark end
    Next i
    
    'Write empty Fitertable
    b1 = &H2: Put #fsff, , b1
    b1 = &H11: Put #fsff, , b1
    b1 = &HFF: Put #fsff, , b1
    b1 = &H22: Put #fsff, , b1
    b1 = &H1: Put #fsff, , b1

    'Write Pattern Data
    b1 = GoatPatternMax
    Put #fsff, , b1
    For i = 0 To GoatPatternMax - 1
        i2 = (GoatPLength(i) / 4)
        b1 = i2
        Put #fsff, , b1
        For i2 = 0 To (GoatPLength(i) - 1)
            i3 = GoatPattern(i, i2)
            b1 = i3
            Put #fsff, , b1
        Next i2
    Next i

    AddTextS vbCrLf + "*** CONVERTED FILE SAVED SUCCESSFULLY TO: *** " + vbCrLf + FS.FileName
    Close #fsff
End Sub
Public Function FormHex(lNumber As Long) As String
    FormHex = Hex(lNumber)
    If Len(FormHex) = 1 Then FormHex = "0" + FormHex
End Function
Public Function FileExist(asPath As String) As Boolean
    If UCase(Dir(asPath)) = UCase(TrimPath(asPath)) Then
      FileExist = True
    Else
      FileExist = False
    End If
End Function
Public Function TrimPath(ByVal asPath As String) As String
    If Len(asPath) = 0 Then Exit Function
    Dim X As Integer
    Do
        X = InStr(asPath, "\")
        If X = 0 Then Exit Do
        asPath = Right(asPath, Len(asPath) - X)
    Loop
    TrimPath = asPath
End Function
Private Sub GoatClear()
    Dim n As String
    Dim i As Long
    'clear header
    Goatfl = 0
    For i = 0 To &H61
        Goatfile(i) = 0
    Next i
    For i = 0 To &HFF
        GoatTableWave(i) = 0
        GoatTablePulse(i) = 0
    Next i
    'GTS2 header name
    GoatAddString "GTS2"
    'Add Name
    Goatfl = 4
    GoatAddString SIDname
    'Add Name
    Goatfl = &H24
    GoatAddString SIDauthor
    'Add Name
    Goatfl = &H44
    GoatAddString SIDreleased
End Sub
Private Function GoatConvertPattern()
    Dim i As Long
    Dim i2 As Long
    Dim i3 As Long
    Dim i4 As Long
    Dim b1 As Long
    Dim nWait As Long
    Dim n As Long
    Dim nNoADSR As Long
    Dim nNoNote As Long
    Dim nGetNext As Long
    Dim nInstrNr As Long
    Dim nComm2 As Long
    Dim nPitch As Long
    Dim pataddr As Long
    Dim gNoteNr As Long
    Dim gInstrument As Long
    Dim gOLDInstrument1 As Long
    Dim gOLDInstrument2 As Long
    Dim gCommandVal1 As Long
    Dim gCommandVal2 As Long
    Dim gTNoNote As Long
    Dim gTMaxPatternLen As Long
    Dim RescInstrNr As Long
    Dim addr As Long
    Dim NewGoatPatternMax
    Dim NewGoatPatternLenght(256) As Long
    Dim NewGoatPattern(256, 8192) As Long 'Pattern number, Pattern Position, 0=Note, 1=Instrument, 2=Command (0-f), 3=Command Value
    Dim TrackIndex(256, 8192) As Long 'Pattern, New Index to Pattern, TrackIndex(Patter, 0) stores new index-list, -1=End
    Dim NewTrackLenght As Long
    Dim NewTrack(256) As Long
    Dim ActTrack As Long
    Dim PNum As Long
    Dim PEndMarker As Boolean

    NewGoatPatternMax = 0
    gTMaxPatternLen = 94 * 4 'Goattracker maximal pattern lenght
    gTNoNote = &HBD        'Goattracker ... Note
    GoatPatternMax = 0
    For i = 0 To 256
        GoatPLength(i) = &H0
        NewGoatPatternLenght(i) = &H0
        For i2 = 0 To 8192
            TrackIndex(i, i2) = -1
            GoatPattern(i, i2) = &H0
            NewGoatPattern(i, i2) = &H0
        Next i2
    Next i
    
    For i = 0 To SIDRHPattternUsed
        addr = SIDfile(SIDRHPatternHi + i) * 256
        addr = addr + SIDfile(SIDRHPatternLo + i)
        addr = addr - SIDloadaddr + SIDhlenght - 1
        
        gInstrument = 0
        gOLDInstrument1 = -1
        gOLDInstrument2 = -2
        gCommandVal1 = 0
        gCommandVal2 = 0
        pataddr = addr
        i2 = 0
        Do
            'Check if Pattern is out of range
            If (pataddr + i2) <= 1 Or (pataddr + i2) >= SIDlenght Then
                'Clear Pattern (empty) and go to next pattern
                GoatPLength(i) = &H8
                GoatPattern(i, 0) = &HBD
                GoatPattern(i, 1) = &H0
                GoatPattern(i, 2) = &H0
                GoatPattern(i, 3) = &H0
                GoatPattern(i, 4) = &HFF
                GoatPattern(i, 5) = &H0
                GoatPattern(i, 6) = &H0
                GoatPattern(i, 7) = &H0
                AddTextS "*** PATTERN $" + Hex(i) + " ADDRESS OUT OF RANGE, CAN'T CONVERT ***"
                GoTo SkipVoice
            End If
            'Set Goattracker Note to "..."
            gNoteNr = gTNoNote
            gCommandVal1 = 0
            gCommandVal2 = 0
            'Get First Byte %ABCDDDDD
            '                A        = 1=Second Byte Follows, A=0 Note Follows
            '                 B       = 1=no new Note follows, just wait for amount DDDDD
            '                  C      = 1=Set no NEW ADSR for Note (change frequency D400/D401 but not D405/d406)
            '                   DDDDD = wait for these amount of frames (0-31)
            b1 = SIDfile(pataddr + i2)
            'Check for Patternend
            If b1 = &HFF Then
                GoatPattern(i, GoatPLength(i)) = &HFF
                GoatPattern(i, GoatPLength(i) + 1) = &H0
                GoatPattern(i, GoatPLength(i) + 2) = &H0
                GoatPattern(i, GoatPLength(i) + 3) = &H0
                GoatPLength(i) = GoatPLength(i) + 4
                Exit Do
            End If
            'Get Commands of Statusbyte in Pattern
            nGetNext = b1 And &H80
            nNoNote = b1 And &H40
            nNoADSR = b1 And &H20
            nWait = b1 And &H1F
            'Check if next byte is followed
            If nGetNext >= 1 Then
                i2 = i2 + 1
                'Get Second Byte %ACCCCCCD
                '                 A        = 1=Do Pitchbend (D=0 Pitchslide down, D=1 Pitchslide Up, CCCCCC=Amount (0-63))
                '                 A        = 0=Set Instrument CCCCCCD (0-127)
                b1 = SIDfile(pataddr + i2)
                'Check events from first byte
                If nNoADSR >= 1 Then
                    'second, make sure instrument is still the same
                    If gOLDInstrument1 = gOLDInstrument2 Then
                        gCommandVal1 = 3     'interpret NoRelease as Portamento (3) in Goattracker, as it doesn't set new ADSR Values
                        gCommandVal2 = &H0  'Portamento should not be heard and as fast as possible, ($FF)
                    End If
                    gOLDInstrument2 = gOLDInstrument1
                    'If gNoteNr = gTNoNote Then
                    '    gNoteNr = &H0
                    '    nNoNote = 0
                    '    gInstrument = 1 'Instrument 1 = killnote
                    'End If
                End If
                
                nPitch = b1 And &H80
                'Check if Pitch bend is used
                If nPitch >= 1 Then
                    'activate pitch
                    If (b1 And &H1) = 0 Then
                        'Bit 1=0 then Pitch down
                        gCommandVal1 = 1
                        gInstrument = 0
                    Else
                        'Bit 1=1 then Pitch up
                        gCommandVal1 = 2
                        gInstrument = 0
                    End If
                    gCommandVal2 = (b1 And &H7F)
                    gCommandVal2 = Int(gCommandVal2 / 4)
                Else
                    'No Pitch, but instrument is changed
                    gInstrument = b1 And &H7F
                    gInstrument = gInstrument + 2
                    'Copy last used instrument to new, needed to check for portamento (Command 3 in GT, no new set of ADSR)
                    gOLDInstrument2 = gOLDInstrument1
                    gOLDInstrument1 = gInstrument
                End If
            End If

            'Check if Note has to follow
            If (nGetNext >= 1) Or (nNoNote = 0) Then
                i2 = i2 + 1
                gNoteNr = SIDfile(pataddr + i2)
                If gNoteNr >= &H5C Then gNoteNr = &H5C
                gNoteNr = gNoteNr + &H60
            End If
            
            'double speed
            'nWait = nWait And 254
            'nWait = nWait / 2
            
            RescInstrNr = -1
            If gNoteNr = gTNoNote And gInstrument <> 0 Then
                gNoteNr = &H60
                RescInstrNr = gInstrument
                gInstrument = &H1
            End If
            
            
            If nWait >= 1 Then
                GoatPattern(i, GoatPLength(i)) = gNoteNr
                GoatPattern(i, GoatPLength(i) + 1) = gInstrument
                GoatPattern(i, GoatPLength(i) + 2) = gCommandVal1
                GoatPattern(i, GoatPLength(i) + 3) = gCommandVal2
                GoatPLength(i) = GoatPLength(i) + 4
                If gCommandVal1 = 3 Then
                    gCommandVal1 = 0
                End If
                
                If nWait >= 1 Then
                    gNoteNr = gTNoNote
                    For i3 = 1 To nWait
                        GoatPattern(i, GoatPLength(i)) = gTNoNote
                        GoatPattern(i, GoatPLength(i) + 1) = &H0
                        GoatPattern(i, GoatPLength(i) + 2) = gCommandVal1
                        GoatPattern(i, GoatPLength(i) + 3) = gCommandVal2
                        GoatPLength(i) = GoatPLength(i) + 4
                    Next i3
                End If
            End If
            
            If RescInstrNr <> -1 Then gInstrument = RescInstrNr
            
            i2 = i2 + 1
        Loop
SkipVoice:
        'Cut Pattern into &HD0 slices (If necessary)
        i3 = 0
        i4 = 0
        For i2 = 0 To GoatPLength(i)
            'if patternlenght exceeds gTMaxPatternLen then create new Pattern to make it Goattracker compatible
            If i3 >= gTMaxPatternLen Then
                'add pattern end
                i3 = i3 And &HFFFC 'align to 4 bytes, just in case :)
                NewGoatPatternLenght(NewGoatPatternMax) = i3
                NewGoatPattern(NewGoatPatternMax, i3) = &HFF
                NewGoatPattern(NewGoatPatternMax, i3 + 1) = &H0
                NewGoatPattern(NewGoatPatternMax, i3 + 2) = &H0
                NewGoatPattern(NewGoatPatternMax, i3 + 3) = &H0
                i3 = 0
                i4 = i4 + 1
                NewGoatPatternMax = NewGoatPatternMax + 1
                AddTextS "Extending Pattern: $" + Hex(i) + " ($" + Hex(NewGoatPatternMax) + ")"
                If NewGoatPatternMax >= &HD0 Then
                    AddTextS "*** TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER ***"
                    Exit Function
                End If
            End If
            TrackIndex(i, i4) = NewGoatPatternMax 'mark indexlist for pattern
            NewGoatPattern(NewGoatPatternMax, i3) = GoatPattern(i, i2)
            NewGoatPatternLenght(NewGoatPatternMax) = i3
            i3 = i3 + 1
        Next i2
        NewGoatPatternMax = NewGoatPatternMax + 1
        If NewGoatPatternMax >= &HD0 Then
            AddTextS "*** TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER ***"
            Exit Function
        End If
                
    'If GoatPLength(i) >= (&H61 * 4) + 1 Then
    '    AddTextS "*** PATTERN $" + Hex(i) + " / LENGTH $" + Hex((GoatPLength(i) - 1) / 4) + " TOO LONG FOR GOATTRACKER ***"
    'End If
    Next i
    
    
    'Overwrite All Old Pattern with new, sliced Pattern
    GoatPatternMax = NewGoatPatternMax
    For i = 0 To NewGoatPatternMax
        GoatPLength(i) = NewGoatPatternLenght(i)
        For i2 = 0 To NewGoatPatternLenght(i)
            GoatPattern(i, i2) = NewGoatPattern(i, i2)
        Next i2
    Next i

    
    'ReIndex old Tracklist to new Tracklist-array (for extended pattern)
    For i = 0 To GoatTracksMax - 1
        PEndMarker = False
        NewTrack(0) = 0
        NewTrackLenght = 0
        For i2 = 1 To (GoatTracks(i, 0) - 1)
            ActTrack = GoatTracks(i, i2)
            If (ActTrack >= &HD0) Or PEndMarker = True Then
                PEndMarker = True
                NewTrack(NewTrackLenght) = ActTrack
                NewTrackLenght = NewTrackLenght + 1
            Else
                i3 = 0
                Do
                    PNum = TrackIndex(ActTrack, i3)
                    If PNum = -1 Then Exit Do
                    NewTrack(NewTrackLenght) = PNum
                    NewTrackLenght = NewTrackLenght + 1
                    If NewTrackLenght >= &HFF Then
                        AddTextS "*** TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER ***"
                        Exit Function
                    End If
                    i3 = i3 + 1
                Loop
            End If
            If NewTrackLenght >= &HFF Then
                AddTextS "*** TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER ***"
                Exit Function
            End If
        Next i2
        GoatTracks(i, 0) = NewTrackLenght
        For i2 = 0 To NewTrackLenght
            GoatTracks(i, i2 + 1) = NewTrack(i2)
        Next i2
    Next i
End Function


Private Function GoatConvertTracks()
    Dim i As Long
    Dim i2 As Long
    Dim i3 As Long
    Dim voice As Long
    Dim so As Long
    Dim b1 As Byte
    Dim b2 As Byte
    Dim wb As Long
    Dim addr As Long
    
    'clear all tracks
    GoatTracksMax = 0
    For i = 0 To 255
        For i2 = 0 To 255
            GoatTracks(i, i2) = &H0
        Next i2
    Next i
    
    Goatfile(&H64) = SIDsubtunes
    For i = 0 To (SIDsubtunes - 1)
        For voice = 0 To 2
            'initialise track with default value
            GoatTracks(GoatTracksMax, 0) = &H4
            GoatTracks(GoatTracksMax, 1) = &H0
            GoatTracks(GoatTracksMax, 2) = &HFF
            GoatTracks(GoatTracksMax, 3) = &H0
            'initialise track with default value
            If voice >= (SIDRHtrackVoices) Then
                GoTo SkipVoice
            Else
                so = voice + (i * (SIDRHtrackVoices * 2))
                addr = SIDfile(SIDRHtrackHi + so) * 256
                addr = addr + SIDfile(SIDRHtrackLo + so)
                addr = addr - SIDloadaddr + SIDhlenght - 1
                If addr <= 1 Or addr >= SIDlenght Then
                    AddTextS "*** SUBTUNE $" + Hex(i) + " (VOICE " + Hex(voice) + ") ADDRESS OUT OF RANGE, CAN'T CONVERT ***"
                    GoTo SkipVoice
                End If
                i2 = 0
                GoatTracks(GoatTracksMax, 0) = 1
                Do
                    b1 = SIDfile(addr + i2)
                    'If track is too long, mark it as trackend
                    If GoatTracks(GoatTracksMax, 0) >= 254 Then
                        b1 = &HFF
                    End If
                    i2 = i2 + 1
                    ' ******************************************
                    ' ************** Player ACE 2 **************
                    ' ******************************************
                    Select Case SIDRHreadTrackVersion
                    Case 4
                        wb = -1
                        '>80 = Repeat song
                        If b1 >= &H80 Then
                            GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = &HFF
                            GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0) + 1) = &H0
                            GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 2
                            Exit Do
                        End If
                    ' ****************************************************
                    ' ************** Player Mega Apocalypse **************
                    ' ****************************************************
                    Case 5, 6, 7, 8
                        wb = -1
                        'transpose + (0-f)
                        If b1 >= &H80 Then
                            If b1 <= &H8F Then
                                wb = b1
                                wb = (wb - &H80) + &HF0 'Goattracker transpose ($FC = +C)
                                GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = wb
                                GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 1
                            End If
                        End If
                        'transpose - (0-f)
                        If b1 >= &HEF Then
                            If b1 <= &HFE Then
                                wb = b1
                                wb = wb Xor &HFF
                                wb = &HF0 - wb 'Goattracker transpose ($E4 = -C)
                                GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = wb
                                GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 1
                            End If
                        End If
                        'end track
                        If b1 = &HFF Then
                            GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = &HFF
                            GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0) + 1) = &H0
                            GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 2
                            Exit Do
                        End If
                        'pattern number
                        If b1 <= &H7F Then
                                GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = b1
                                GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 1
                        End If
                    ' ****************************************************
                    ' ****************** Player Warhawk ******************
                    ' ****************************************************
                    Case 0, 1, 2, 3, 4
                        wb = -1
                        'stop track
                        If b1 = &HFE Then
                            If b1 <= &HFE Then
                                GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = &HFF
                                GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0) + 1) = &HFD 'make repeat illegal, so goattracker stops
                                GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 3
                                Exit Do
                            End If
                        End If
                        'end track
                        If b1 = &HFF Then
                            GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = &HFF
                            GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0) + 1) = &H0
                            GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 3
                            Exit Do
                        End If
                        'pattern number
                        If b1 <= &HFD Then
                                GoatTracks(GoatTracksMax, GoatTracks(GoatTracksMax, 0)) = b1
                                GoatTracks(GoatTracksMax, 0) = GoatTracks(GoatTracksMax, 0) + 1
                        End If
                    End Select
                Loop
            End If
SkipVoice:
        GoatTracksMax = GoatTracksMax + 1
        Next voice
    Next i

End Function
Private Sub GoatAddString(SString As String)
    Dim i As Long
    Dim n As String
    If Len(SString) >= 1 Then
        For i = 1 To Len(SString)
            n = Mid(SString, i, 1)
            Goatfile(Goatfl) = Asc(n)
            Goatfl = Goatfl + 1
        Next i
    End If
End Sub
Private Function SSearchfile(SString As String) As Long
    Dim snumbers As Long
    Dim snumb(99) As Long
    Dim i As Long
    Dim ix As Long
    Dim ixf As Long
    Dim inumb As Long
    Dim findnumbers As Long
    Dim ss As String
    
    SSearchfile = -1
    snumbers = (Len(SString) + 1) / 3
    
    findnumbers = 0
    inumb = 0
    For i = 1 To Len(SString) Step 3
        ss = UCase(Mid(SString, i, 2))
        If ss = "??" Then
            snumb(inumb) = -1
        Else
            snumb(inumb) = HexToDec(ss)
            findnumbers = findnumbers + 1
        End If
        inumb = inumb + 1
    Next i
    
    i = 1
    Do While i <= (SIDlenght - inumb)
    ix = 0
    ixf = 0
        Do While ix <= inumb
        If snumb(ix) <> -1 Then
            If snumb(ix) = SIDfile(i + ix) Then
                ixf = ixf + 1
                If ixf >= findnumbers Then
                    SSearchfile = i
                    Exit Function
                End If
            Else
                Exit Do
            End If
        End If
        ix = ix + 1
        Loop
    i = i + 1
    Loop
    SSearchfile = -1
End Function

Private Function HexToDec(ByVal xHex As String) As Long
    Dim i As Long
    Dim z As Long
    Dim nval As Long
    Dim c As Double
    Dim nl As Long
    
    nl = Len(xHex)
    xHex = UCase(xHex)
    c = 0
    For i = nl To 1 Step -1
        nval = InStr(1, "0123456789ABCDEF", Mid(xHex, (nl - i) + 1, 1))
        If nval >= 1 Then
            nval = nval - 1
            c = c + (nval * (16 ^ (i - 1)))
        End If
    Next i
    HexToDec = c
End Function

